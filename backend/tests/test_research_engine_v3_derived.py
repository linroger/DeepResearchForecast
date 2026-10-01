"""RESEARCH-8: declarative DERIVED findings in v3.

RESEARCH_DERIVED_FINDINGS (default false):

* off — postprocess output, the KIQ task, the section rules, the digest,
  sources.json and meta are exactly what they were;
* on — the KIQ task asks for a "(DERIVED: <formula>; a=<value> [S<n>], …)"
  clause on every calculated figure and postprocess_notes recomputes it with
  zero model calls: single-source operands on the fetched page they cite, a
  stated number equal to the result.  Such a fact is DERIVED (never
  VERIFIED); any failure is UNVERIFIED with a derivation_error.  The digest
  shows the calculation, fallback sections publish DERIVED facts, gap rounds
  and meta.kiqs.verified count VERIFIED only, sources.json gains a separate
  derived_supports field the report's citation spans read, unverified quant
  rows stating a DERIVED result gain derived_from, verified_facts.json
  projects DERIVED facts as "derived", and meta gains kiqs.derived and
  derived.

Offline: the scripted model, injected search/fetch and real bridge of
``test_research_engine_v3``.
"""

from __future__ import annotations

import datetime as _dt
import functools
import hashlib
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

import test_absence_discipline as ad
import test_research_engine_v3 as v3
import test_research_engine_v3_evidence as ev
from app.services.report_agent import ReportAgent
from test_orchestrator_research_wiring import _launch_capturing_child

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg
po = v3.po
dn = lr.dn

KIQ_RULE = ("Derived figures: when a finding states a growth rate, ratio, share or other figure you calculated, "
            "write it as a calculation and end the finding with (DERIVED: <formula>; a=<value> [S<n>], "
            "b=<value> [S<n>]) using values exactly as on one fetched page; use names, not numbers, in the formula.")
SECTION_RULE = ("- (DERIVED) findings are calculations from the cited figures: state them as calculations "
                "(implying about X, calculated from [S<n>]), never as reported values.")
# AGENT_TOOLS as bound on every agent call (and the prime call) before this package.
AGENT_TOOLS_SHA256 = "ade874b5c6dbd8ad2803e8e11a6888eade789a8b3b20e162fe12ad60815af25f"

S12_PAGE = ("# Capacity statistics\n\nInstalled capacity reached 37 GW in 2024, up from 13 GW in 2019, the "
            "agency said. Grid operators added 2.5 GW of storage.")
S13_PAGE = "Annual review: output was 13 GW in 2019 across the region."
ROWS = {
    12: {"sid": 12, "fetched": True, "title": "Capacity statistics", "snippet": ""},
    13: {"sid": 13, "fetched": True, "title": "Annual review", "snippet": ""},
    14: {"sid": 14, "fetched": False, "title": "Outlook note", "snippet": "Capacity of 37 GW and 13 GW."},
}
PAGES = {12: S12_PAGE, 13: S13_PAGE}
FINDING = "Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 [S12], b=13 [S12])"


def page_numbers(sid):
    return lr.page_number_set(PAGES[sid]) if sid in PAGES else None


def findings(*lines: str) -> str:
    return ev.findings(*(f"- {line}" for line in lines))


def post(*lines: str, derivations: bool = True, mode: str = "off", rows=None) -> list[dict]:
    rows = ROWS if rows is None else rows
    return lr.postprocess_notes("K1", findings(*lines), rows.get, page_numbers, evidence_mode=mode,
                                page_text=PAGES.get, derivations=derivations)[1]["facts"]


def only(*lines: str, **kwargs) -> dict:
    (fact,) = post(*lines, **kwargs)
    return fact


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assert_recomputable(fact: dict, rows, pages) -> None:
    """The invariant of a DERIVED fact: a single-source derivation, shown and
    fetched, whose every operand is on that page and whose formula recomputes
    to the recorded result, stated by the fact."""
    derivation = fact["derivation"]
    sid = derivation["sid"]
    assert fact["tag"] == "DERIVED" and sid in fact["sids"] and rows[sid]["fetched"]
    page = lr.page_number_set(pages[sid])
    values = {}
    for name, operand in derivation["operands"].items():
        if operand["sid"] is None:
            values[name] = dn.period_value(operand["value"])
            continue
        assert operand["sid"] == sid
        tokens = lr._operand_tokens(operand["value"])
        assert tokens and not lr._missing_numbers(operand["value"], tokens, page)
        values[name] = lr._operand_decimal(operand["value"])
    assert dn.format_exact(dn.evaluate(derivation["expr"], values)) == derivation["result"]


# ================================================================== postprocess

CORPUS = [
    FINDING,
    "Capacity grew about 185% (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])",
    "Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=38 GW [S12], b=13 GW [S12])",
    "Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S13])",
    "Capacity grew about 123% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12]) (VERIFIED)",
    "装机容量增长约185% [S12]（推算：(a-b)/b*100；a=37 GW [S12]，b=13 GW [S12]）",
    "Installed capacity reached 37 GW in 2024 [S12] (VERIFIED)",
    "Capacity grew about 185% [S12] (VERIFIED) EVIDENCE: \"Installed capacity reached 37 GW in 2024, up from "
    "13 GW in 2019\" (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])",
]


def test_flag_off_postprocess_output_is_identical_and_keeps_the_clause_in_the_text():
    notes = findings(*CORPUS)
    for mode in ("off", "audit", "enforce"):
        legacy = lr.postprocess_notes("K1", notes, ROWS.get, page_numbers, evidence_mode=mode, page_text=PAGES.get)
        assert lr.postprocess_notes("K1", notes, ROWS.get, page_numbers, evidence_mode=mode, page_text=PAGES.get,
                                    derivations=False) == legacy
        facts = legacy[1]["facts"]
        assert all("derivation" not in f and "derivation_error" not in f and f["tag"] != "DERIVED" for f in facts)
    off = lr.postprocess_notes("K1", notes, ROWS.get, page_numbers)[1]["facts"]
    assert "(DERIVED: (a-b)/b*100" in off[0]["text"] and off[0]["tag"] == "REPORTED"


def test_a_recomputed_single_source_derivation_is_derived_with_its_result():
    fact = only(FINDING)
    assert fact == {"kiq": "K1", "text": "Capacity grew about 185% [S12]", "sids": [12], "tag": "DERIVED",
                    "verified_numbers": None,
                    "derivation": {"expr": "(a-b)/b*100",
                                   "operands": {"a": {"value": "37", "sid": 12}, "b": {"value": "13", "sid": 12}},
                                   "result": "184.615384615", "sid": 12}}
    assert_recomputable(fact, ROWS, PAGES)


FAILURE_CASES = [
    # An operand that is not on the cited page.
    ("Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=38 GW [S12], b=13 GW [S12])", "operand_not_on_page"),
    ("Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GWh [S12])", "operand_not_on_page"),
    ("Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13% [S12])", "operand_not_on_page"),
    ("Capacity rose 2.8x [S12] (DERIVED: a/b; a=37 GW [S12], b=5 [S12])", "operand_not_on_page"),
    # A source the agent was not shown (its marker is stripped), or saw only in search results.
    ("Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S99], b=13 GW [S12])", "unshown_source"),
    ("Capacity grew about 185% [S14] (DERIVED: (a-b)/b*100; a=37 GW [S14], b=13 GW [S14])", "unshown_source"),
    ("Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW)", "unshown_source"),
    # Operands from two sources, or from a source the finding does not cite.
    ("Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S13])", "cross_source"),
    ("Capacity grew about 185% [S13] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])", "cross_source"),
    # A literal, an unknown name, an unreadable clause.
    ("Capacity grew about 185% [S12] (DERIVED: (37-13)/13*100; a=37 GW [S12], b=13 GW [S12])", "eval_error"),
    ("Capacity grew about 185% [S12] (DERIVED: (a-c)/b*100; a=37 GW [S12], b=13 GW [S12])", "eval_error"),
    ("Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100)", "eval_error"),
    # The stated number is not the result, or the finding states none.
    ("Capacity grew about 123% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])", "result_mismatch"),
    ("Capacity grew strongly to 37 GW [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])",
     "no_result_token"),
]


@pytest.mark.parametrize("line, code", FAILURE_CASES)
def test_every_failed_check_is_unverified_with_its_derivation_error(line, code):
    fact = only(line)
    assert fact["tag"] == "UNVERIFIED" and fact["derivation_error"] == code and "derivation" not in fact
    assert "DERIVED" not in fact["text"]


def test_the_clause_replaces_the_tag_the_agent_wrote():
    for tag in ("(VERIFIED)", "(REPORTED)", "(已核实)", ""):
        fact = only(f"Capacity grew about 185% [S12] {tag} (DERIVED: (a-b)/b*100; a=37 [S12], b=13 [S12])")
        assert fact["tag"] == "DERIVED" and fact["text"] == "Capacity grew about 185% [S12]"
    # A tag written after the clause is split off too.
    fact = only("Capacity grew about 123% [S12] (DERIVED: (a-b)/b*100; a=37 [S12], b=13 [S12]) (VERIFIED)")
    assert fact["tag"] == "UNVERIFIED" and fact["text"] == "Capacity grew about 123% [S12]"


def test_the_derivation_forms_the_engine_reads():
    cases = {
        # Markers only in the clause: the finding cites the clause's source.
        "Capacity grew about 185% (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])": "184.615384615",
        # The Chinese clause with full-width punctuation.
        "装机容量增长约185% [S12]（推算：（a－b）／b×100；a=37 GW [S12]，b=13 GW [S12]）": "184.615384615",
        # A compound annual rate over a whole-year period.
        ("Capacity grew about 23.3% a year from 2019 to 2024 [S12] "
         "(DERIVED: ((a/b)**(1/n)-1)*100; a=37 GW [S12], b=13 GW [S12], n=years(2019,2024))"): "23.2683759853",
        # A ratio written as a percentage, and a figure at a stated scale.
        "Capacity is about 285% of its 2019 level [S12] (DERIVED: a/b; a=37 GW [S12], b=13 GW [S12])": "2.84615384615",
        "Storage added about 2,500 MW [S12] (DERIVED: a*1000; a=2.5 GW [S12])": "2500",
        "The gap is about 0.024 thousand GW [S12] (DERIVED: (a-b)/1000; a=37 GW [S12], b=13 GW [S12])": "0.024",
        # Clause in the middle, marker after it, an unclosed clause.
        "Capacity grew about 185% (DERIVED: (a-b)/b*100; a=37 [S12], b=13 [S12]) [S12]": "184.615384615",
        "Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 [S12], b=13 [S12]": "184.615384615",
        # A negative operand.
        "The swing was about 50 GW [S12] (DERIVED: a-b; a=37 GW [S12], b=-13 GW [S12])": "50",
    }
    for line, result in cases.items():
        fact = only(line)
        assert fact["tag"] == "DERIVED", (line, fact)
        assert fact["derivation"]["result"] == result and "DERIVED" not in fact["text"] and "推算" not in fact["text"]
        assert_recomputable(fact, ROWS, PAGES)
    scaled = only("The capacity is $1.2 trillion [S12] (DERIVED: a*b; a=37 [S12], b=13 [S12])")
    assert scaled["tag"] == "UNVERIFIED" and scaled["derivation_error"] == "result_mismatch"


def test_a_second_clause_only_the_last_is_read_and_the_evidence_clause_comes_first():
    fact = only("Capacity grew about 185% [S12] (DERIVED: a; a=13 [S12]) (DERIVED: (a-b)/b*100; a=37 [S12], "
                "b=13 [S12])")
    assert fact["tag"] == "DERIVED" and fact["text"].startswith("Capacity grew about 185% [S12] (DERIVED: a;")
    quote = "Installed capacity reached 37 GW in 2024, up from 13 GW in 2019"
    for line in (f'Capacity grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 [S12], b=13 [S12]) EVIDENCE: "{quote}"',
                 f'Capacity grew about 185% [S12] EVIDENCE: "{quote}" (DERIVED: (a-b)/b*100; a=37 [S12], b=13 [S12])'):
        for mode in ("audit", "enforce"):
            fact = only(line, mode=mode)
            assert fact["tag"] == "DERIVED" and fact["claimed_tag"] == "DERIVED", (mode, line)
            assert fact["text"] == "Capacity grew about 185% [S12]" and fact["evidence_status"] == "verified"


def test_enforce_demotes_a_derived_fact_whose_quote_is_invented_and_gap_rounds_never_count_it():
    invented = "The minister told parliament that capacity had nearly tripled since the base year"
    fact = only(f'Capacity grew about 185% [S12] (VERIFIED) EVIDENCE: "{invented}" '
                "(DERIVED: (a-b)/b*100; a=37 [S12], b=13 [S12])", mode="enforce")
    assert fact["tag"] == "UNVERIFIED" and fact["verification"] == "evidence_not_on_page"
    assert fact["claimed_tag"] == "DERIVED"
    derived = only(FINDING, mode="enforce")
    for item in (fact, derived, only(FINDING)):
        assert not lr._gap_counts_verified(item, enforce=True) and not lr._gap_counts_verified(item, enforce=False)
    assert lr._gap_counts_verified(only("Installed capacity reached 37 GW in 2024 [S12] (VERIFIED)"), enforce=False)
    summary = lr.evidence_summary([{"evidence_contract": "enforce:v1", "facts": [fact, derived]}], "enforce")
    assert summary["claimed_verified"] == {"facts": 0, "located": 0}


def test_no_derived_fact_exists_without_a_recomputable_single_source_derivation():
    """Every clause form of the corpus and of the failure cases: whatever is
    DERIVED recomputes from operands on its one fetched page."""
    lines = [*CORPUS, *(line for line, _ in FAILURE_CASES)]
    derived = 0
    for mode in ("off", "audit", "enforce"):
        for fact in post(*lines, mode=mode):
            if fact["tag"] == "DERIVED":
                derived += 1
                assert_recomputable(fact, ROWS, PAGES)
            else:
                assert "derivation" not in fact or fact.get("verification") == "evidence_not_on_page"
    assert derived >= 3


def test_derived_summary_counts_clauses_admissions_and_rejections():
    facts = post(*CORPUS)
    # A resumed record's unreadable derivation_error counts as a clause, under no code.
    unreadable = {"tag": "UNVERIFIED", "derivation_error": ["eval_error"]}
    summary = lr.derived_summary([{"facts": facts}, {"facts": [{"tag": "VERIFIED"}, "junk", unreadable]}])
    assert summary == {"facts": 8, "admitted": 4, "rejected": {
        "operand_not_on_page": 1, "unshown_source": 0, "cross_source": 1, "eval_error": 0,
        "result_mismatch": 1, "no_result_token": 0}}
    assert lr.derived_summary([]) == {"facts": 0, "admitted": 0, "rejected": dict.fromkeys(lr.DERIVED_ERRORS, 0)}


# ================================================================== prompts

def _kiq_engine(*, derived: bool | None, absence: bool = False, evidence: str = "off"):
    engine = ad._kiq_engine(absence_on=absence, evidence=evidence)
    if derived is not None:
        engine.derived_findings = derived
    return engine


def _section_engine(*, derived: bool | None, absence: bool = False):
    engine = ad._section_engine(absence_on=absence)
    if derived is not None:
        engine.derived_findings = derived
    return engine


def test_rule_texts_are_the_specified_lines():
    assert lr._KIQ_DERIVED_RULE == KIQ_RULE
    assert lr._SECTION_DERIVED_RULE == SECTION_RULE


def test_flag_off_tasks_are_identical_and_on_appends_the_rules_in_canonical_order():
    off = ad._kiq_task(_kiq_engine(derived=False))
    assert _sha(off) == ev.KIQ_TASK_SHA256
    assert ad._kiq_task(_kiq_engine(derived=None)) == off
    assert ad._kiq_task(_kiq_engine(derived=True)) == off + "\n" + KIQ_RULE
    # Absence (RESEARCH-3), evidence (RESEARCH-7), derivation (RESEARCH-8).
    assert ad._kiq_task(_kiq_engine(derived=True, absence=True, evidence="audit")) == "\n".join(
        [off, lr._KIQ_ABSENCE_RULE, lr._KIQ_EVIDENCE_RULE, KIQ_RULE])
    for kwargs, pinned in (({}, ad.SECTION_TASK_SHA256),
                           ({"note": "Fix the citation.", "current": "Old body [S1]."}, ad.SECTION_REWRITE_TASK_SHA256)):
        section_off = lr._Engine.section_task(_section_engine(derived=False), ad._SECTIONS, **kwargs)
        assert _sha(section_off) == pinned
        assert lr._Engine.section_task(_section_engine(derived=None), ad._SECTIONS, **kwargs) == section_off
        on = lr._Engine.section_task(_section_engine(derived=True, absence=True), ad._SECTIONS, **kwargs)
        # Absence (RESEARCH-3), then DERIVED, right after the rules.
        block = "\n".join([lr._SECTION_RULES, lr._SECTION_ABSENCE_RULE, SECTION_RULE])
        assert block in on and on.replace(block, lr._SECTION_RULES, 1) == section_off


def test_engine_core_and_agent_tools_are_unchanged():
    assert _sha(lr.ENGINE_CORE) == ev.ENGINE_CORE_SHA256
    assert lr.AGENT_TOOLS is rg.AGENT_TOOLS_SCHEMA
    assert _sha(json.dumps(lr.AGENT_TOOLS, sort_keys=True, ensure_ascii=False)) == AGENT_TOOLS_SHA256


# ================================================================== digest and fallback sections

def _record(facts: list[dict]) -> dict:
    return {"id": "K1", "question": "How fast did capacity grow?", "facts": facts, "conflicts": [],
            "open_questions": []}


def test_the_digest_shows_the_calculation_of_a_derived_fact():
    facts = post(FINDING, "Installed capacity reached 37 GW in 2024 [S12] (VERIFIED)",
                 "Capacity grew about 123% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])")
    block, dropped = lr._kiq_digest_block(_record(facts), 12000, "English")
    assert dropped == 0
    assert block.splitlines()[2:] == [
        "- Installed capacity reached 37 GW in 2024 [S12] (VERIFIED)",
        "- Capacity grew about 185% [S12] (DERIVED from [S12]: (a-b)/b*100; a=37, b=13)",
        "- Capacity grew about 123% [S12] (UNVERIFIED)"]
    # Over its cap a block drops UNVERIFIED, then REPORTED, then DERIVED, then VERIFIED lines.
    record = _record([*facts, *post("Outlook notes expect further growth [S12] (REPORTED)")])
    full = lr._kiq_digest_block(record, 12000, "English")[0].splitlines()[2:]
    dropped_order: list[str] = []
    for cap in range(len("\n".join(full)) + 200, 0, -1):
        kept = lr._kiq_digest_block(record, cap, "English")[0].splitlines()
        dropped_order += [line for line in full if line not in kept and line not in dropped_order]
    tags = ("UNVERIFIED", "REPORTED", "DERIVED", "VERIFIED")
    assert [next(tag for tag in tags if f"({tag}" in line) for line in dropped_order] == list(tags)
    # A hindcast's citation wall that strips the derivation's marker leaves a bare tag.
    walled = lr.pit_wall_record(_record([dict(facts[0], text="Capacity grew about 185% [S12][S3]")]),
                                lambda sid: sid != 12)[0]
    assert "(DERIVED)" in lr._kiq_digest_block(walled, 12000, "English")[0]
    assert "[S12]" not in lr._kiq_digest_block(walled, 12000, "English")[0]


def test_fallback_sections_publish_derived_facts_but_never_unverified_ones():
    facts = post(FINDING, "Capacity grew about 123% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])",
                 "Outlook notes expect further growth [S12] (REPORTED)")
    sections = [lr.OutlineSection(index=1, title="Capacity growth", kiq_ids=["K1"], focus="growth")]
    body = lr.fallback_section_bodies(sections, {"K1": _record(facts)}, "English")[1]
    assert body.splitlines() == ["- Capacity grew about 185% [S12]", "- Outlook notes expect further growth [S12]"]


# ================================================================== quant rows

def _quant_engine(tmp_path: Path, *, derived: bool | None):
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    s12 = ledger.register("https://agency.gov/capacity", "Capacity statistics", "")
    ledger.mark_fetched(s12["sid"], content_sha256="x", chars=10, page_path=str(tmp_path / "p1.txt"))
    s13 = ledger.register("https://review.org/annual", "Annual review", "")
    ledger.mark_fetched(s13["sid"], content_sha256="y", chars=10, page_path=str(tmp_path / "p2.txt"))
    pages = {s12["sid"]: lr.page_number_set(S12_PAGE), s13["sid"]: lr.page_number_set(S13_PAGE)}
    fact = only(FINDING)
    fact["derivation"]["sid"] = s12["sid"]
    for operand in fact["derivation"]["operands"].values():
        operand["sid"] = s12["sid"]
    lines: list[tuple[str, str]] = []
    engine = types.SimpleNamespace(ledger=ledger, page_numbers=pages.get, meta={}, analytics_errors=[],
                                   records={"K1": _record([fact])},
                                   log=lambda kind, message: lines.append((kind, message)))
    if derived is not None:
        engine.derived_findings = derived
    for name in ("_verify_quant_rows", "_derive_quant_rows", "_derived_facts"):
        setattr(engine, name, functools.partial(getattr(lr._Engine, name), engine))
    rows = [{"metric": "growth", "value": "185", "unit": "%", "source_url": s12["url"]},
            {"metric": "growth", "value": "184.6", "unit": "%", "source_url": s12["url"]},
            {"metric": "growth", "value": "190", "unit": "%", "source_url": s12["url"]},
            {"metric": "growth", "value": "185", "unit": "%", "source_url": s13["url"]},
            {"metric": "capacity", "value": "37", "unit": "GW", "source_url": s12["url"]},
            {"metric": "growth", "value": "180-190", "unit": "%", "source_url": s12["url"]}]
    return engine, rows, s12["sid"]


def test_an_unverified_quant_row_stating_a_derived_result_gains_derived_from(tmp_path):
    engine, rows, sid = _quant_engine(tmp_path, derived=True)
    lr._Engine._quant_provenance(engine, rows, _dt.date(2026, 10, 1), verify=True, typing=False)
    assert [row["verification"] for row in rows] == ["unverified"] * 4 + ["verified", "unverified"]
    expected = {"sid": sid, "expr": "(a-b)/b*100", "result": "184.615384615"}
    assert [row.get("derived_from") for row in rows] == [expected, expected, None, None, None, None]
    assert engine.meta["quant_provenance"]["derived_from"] == 2
    assert engine.meta["quant_provenance"]["verification_hist"] == {"unverified": 5, "verified": 1}


@pytest.mark.parametrize("derived", [False, None])
def test_flag_off_quant_rows_get_no_derived_from(tmp_path, derived):
    engine, rows, _ = _quant_engine(tmp_path, derived=derived)
    lr._Engine._quant_provenance(engine, rows, _dt.date(2026, 10, 1), verify=True, typing=False)
    assert not any("derived_from" in row for row in rows)
    assert "derived_from" not in engine.meta["quant_provenance"]


def test_derived_from_needs_the_verified_facts_verification(tmp_path):
    engine, rows, _ = _quant_engine(tmp_path, derived=True)
    lr._Engine._quant_provenance(engine, rows, _dt.date(2026, 10, 1), verify=False, typing=True)
    assert not any("derived_from" in row or "verification" in row for row in rows)


def test_a_failing_derived_match_degrades_safe_and_keeps_the_verification(tmp_path, monkeypatch):
    engine, rows, _ = _quant_engine(tmp_path, derived=True)

    def broken(row, derivations):
        raise RuntimeError("matcher exploded")

    monkeypatch.setattr(lr, "derived_quant_match", broken)
    lr._Engine._quant_provenance(engine, rows, _dt.date(2026, 10, 1), verify=True, typing=False)
    assert [row["verification"] for row in rows] == ["unverified"] * 4 + ["verified", "unverified"]
    assert not any("derived_from" in row for row in rows)
    assert engine.analytics_errors == [{"helper": "quant_provenance:derived", "error": "RuntimeError: matcher exploded"}]
    assert "derived_from" not in engine.meta["quant_provenance"]


def test_derived_quant_match_reads_one_number_at_its_precision_and_scale():
    derivation = {"sid": 1, "expr": "a*b", "result": "1200000000000"}
    assert lr.derived_quant_match({"value": "1.2", "unit": "trillion USD"}, [derivation]) is derivation
    assert lr.derived_quant_match({"value": "1,200", "unit": "billion USD"}, [derivation]) is derivation
    assert lr.derived_quant_match({"value": "1.3", "unit": "trillion USD"}, [derivation]) is None
    assert lr.derived_quant_match({"value": "1.2E12", "unit": "USD"}, [derivation]) is None
    assert lr.derived_quant_match({"value": "185", "unit": "%"}, [{"result": "bogus"}, {"result": "1.846"}]) == {
        "result": "1.846"}


# ================================================================== report spans

def test_report_citation_spans_read_derived_supports_after_supports():
    source = {"title": "Capacity statistics", "supports": ["Installed capacity reached 37 GW in 2024"],
              "excerpt": "Installed capacity reached 37 GW in 2024. Up from 13 GW in 2019."}
    legacy = ReportAgent._citation_evidence_spans(source)
    assert legacy == ["Capacity statistics", "Installed capacity reached 37 GW in 2024",
                      "Installed capacity reached 37 GW in 2024.", "Up from 13 GW in 2019."]
    statement = "Capacity grew about 185% [calculated: (a-b)/b*100; a=37 GW, b=13 GW]"
    with_derived = dict(source, derived_supports=[statement, " "])
    assert ReportAgent._citation_evidence_spans(with_derived) == [*legacy[:2], statement, *legacy[2:]]
    line = "Capacity grew about 185% between 2019 and 2024 [S1]."
    assert ReportAgent._semantic_citation_support(line, source) is not True
    assert ReportAgent._semantic_citation_support(line, with_derived) is True


# ================================================================== engine runs

DERIVED_OK = ("Installed capacity grew about 17.3% from 2022 to 2023 [S{cite}] "
              "(DERIVED: (a-b)/b*100; a=176 GW [S{cite}], b=150 GW [S{cite}])")
DERIVED_BAD = ("Capacity grew about 25% in 2023 [S{cite}] "
               "(DERIVED: (a-b)/b*100; a=176 GW [S{cite}], b=150 GW [S{cite}])")


class DerivedWorld(v3.World):
    """The base findings plus a derived finding that recomputes and one that does not."""

    def notes(self, tool_results) -> str:
        cite, _ = ev._sids(tool_results)
        base = super().notes(tool_results)
        return base.replace("## Findings\n", "## Findings\n" + "\n".join(
            f"- {line.format(cite=cite)}" for line in (DERIVED_OK, DERIVED_BAD)) + "\n", 1)


class DerivedOnlyWorld(v3.World):
    """Every finding is a derivation that recomputes: no VERIFIED fact at all."""

    def notes(self, tool_results) -> str:
        cite, _ = ev._sids(tool_results)
        return findings(*(line.format(cite=cite) for line in (
            DERIVED_OK,
            "Capacity rose about 26 GW in 2023 [S{cite}] (DERIVED: a-b; a=176 GW [S{cite}], b=150 GW [S{cite}])",
            "Capacity was about 1.17 times its 2022 level [S{cite}] "
            "(DERIVED: a/b; a=176 GW [S{cite}], b=150 GW [S{cite}])")))


def _records(out: Path) -> dict[str, dict]:
    return ev._records(out)


def _derived_facts(records: dict[str, dict]) -> list[dict]:
    return [fact for record in records.values() for fact in record["facts"] if fact["tag"] == "DERIVED"]


def test_flag_off_runs_are_byte_identical(tmp_path, bridge, monkeypatch):
    """Off (default, explicit false or a non-boolean value): the same model
    calls and the same records, report and sources.json, with no
    derived_supports, no DERIVED fact and no derived meta."""
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    outs = []
    for name, value in (("default", None), ("false", "false"), ("bogus", "sometimes")):
        monkeypatch.delenv("RESEARCH_DERIVED_FINDINGS", raising=False)
        if value is not None:
            monkeypatch.setenv("RESEARCH_DERIVED_FINDINGS", value)
        rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, DerivedWorld(), out_dir=tmp_path / name)
        assert rc == 0 and meta["status"] == "completed"
        tasks = ev._kiq_tasks(model)
        assert tasks and all(KIQ_RULE not in task for task in tasks)
        assert all(SECTION_RULE not in call["messages"][-1][1] for call in v3.calls_of(model, "SECTION WRITING TASK"))
        assert "derived" not in meta and "derived" not in meta["kiqs"]
        assert not any("derived_supports" in row for row in ev._load(out / "sources.json"))
        records = _records(out)
        assert all(f["tag"] != "DERIVED" and "derivation" not in f for r in records.values() for f in r["facts"])
        assert any("(DERIVED: (a-b)/b*100" in f["text"] for r in records.values() for f in r["facts"])
        outs.append((out, [call["messages"] for call in model.calls]))
    first, first_calls = outs[0]
    for out, calls in outs[1:]:
        assert calls == first_calls
        for name in ("sources.json", "quantitative.json", "research_report.md", "verified_facts.json"):
            assert (out / name).read_bytes() == (first / name).read_bytes(), name
        assert [record["facts"] for record in _records(out).values()] == \
            [record["facts"] for record in _records(first).values()]


def test_flag_on_derives_without_extra_model_calls(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    rc, _, _, off_model, _ = v3.run_engine(tmp_path, bridge, DerivedWorld(), out_dir=tmp_path / "off")
    assert rc == 0
    monkeypatch.setenv("RESEARCH_DERIVED_FINDINGS", "true")
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, DerivedWorld(), out_dir=tmp_path / "on")
    assert rc == 0 and meta["status"] == "completed"
    # Zero additional LLM calls, the same system prompt and tools; only volatile task text changed.
    assert [v3.role_of(call) for call in model.calls] == [v3.role_of(call) for call in off_model.calls]
    assert ev._systems(model) == ev._systems(off_model) == {lr.ENGINE_CORE}
    assert all(call["tools"] == lr.AGENT_TOOLS for call in model.calls if call["tools"] is not None)
    tasks = ev._kiq_tasks(model)
    assert tasks and all(task.endswith("\n" + KIQ_RULE) for task in tasks)
    assert {task[:-len(KIQ_RULE) - 1] for task in tasks} == ev._kiq_tasks(off_model)
    writers = v3.calls_of(model, "SECTION WRITING TASK")
    assert writers and all(lr._SECTION_RULES + "\n" + SECTION_RULE in call["messages"][-1][1] for call in writers)
    # The digest every writer reads shows the calculation.
    assert all(re.search(r"\(DERIVED from \[S\d+\]: \(a-b\)/b\*100; a=176 GW, b=150 GW\)", call["messages"][2][1])
               for call in writers)
    records = _records(out)
    n = len(records)
    pages = {}
    ledger = {row["sid"]: row for row in ev._load(out / "v3" / "sources_ledger.json")}
    for record in records.values():
        tags = [fact["tag"] for fact in record["facts"]]
        assert tags[:2] == ["DERIVED", "UNVERIFIED"] and record["facts"][1]["derivation_error"] == "result_mismatch"
        fact = record["facts"][0]
        sid = fact["derivation"]["sid"]
        pages[sid] = v3.page_text(ledger[sid]["url"])
        assert_recomputable(fact, ledger, pages)
        assert fact["derivation"]["result"] == "17.3333333333"
    assert meta["derived"] == {"facts": 2 * n, "admitted": n, "rejected": {
        "operand_not_on_page": 0, "unshown_source": 0, "cross_source": 0, "eval_error": 0, "result_mismatch": n,
        "no_result_token": 0}}
    assert meta["kiqs"]["derived"] == n
    assert meta["kiqs"]["verified"] == sum(f["tag"] == "VERIFIED" for r in records.values() for f in r["facts"])
    assert _load_meta(out)["derived"] == meta["derived"]
    # sources.json: every row carries derived_supports; the derivation sources hold the statement.
    sources = ev._load(out / "sources.json")
    by_url = {row["url"]: row for row in sources}
    assert all(isinstance(row["derived_supports"], list) for row in sources)
    statement = ("Installed capacity grew about 17.3% from 2022 to 2023 "
                 "[calculated: (a-b)/b*100; a=176 GW, b=150 GW]")
    cited = [by_url[ledger[sid]["url"]] for sid in pages if ledger[sid]["url"] in by_url]
    assert cited and all(row["derived_supports"] == [statement] for row in cited)
    assert all(statement not in row["supports"] for row in sources)            # never merged into supports
    assert all(len(text) <= lr.EVIDENCE_SUPPORT_CHARS for row in sources for text in row["derived_supports"])
    # verified_facts.json projects DERIVED facts as "derived", never "verified".
    projected = ev._load(out / "verified_facts.json")
    statuses = [fact["status"] for fact in projected["facts"]]
    assert statuses.count("derived") == n and projected["counts"]["verified"] == statuses.count("verified")
    assert all(fact["spans"] == [] for fact in projected["facts"] if fact["status"] == "derived")


def _load_meta(out: Path) -> dict:
    return ev._load(out / "meta.json")


def test_flag_on_sources_differ_from_off_only_by_derived_supports(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    rc, _, _, _, off = v3.run_engine(tmp_path, bridge, DerivedWorld(), out_dir=tmp_path / "off")
    assert rc == 0
    monkeypatch.setenv("RESEARCH_DERIVED_FINDINGS", "true")
    rc, _, _, _, on = v3.run_engine(tmp_path, bridge, DerivedWorld(), out_dir=tmp_path / "on")
    assert rc == 0
    off_rows, on_rows = ev._load(off / "sources.json"), ev._load(on / "sources.json")
    assert [row["url"] for row in on_rows] == [row["url"] for row in off_rows]
    for row, base in zip(on_rows, off_rows, strict=True):
        assert "derived_supports" not in base
        assert {k: v for k, v in row.items() if k != "derived_supports"} == base
        assert list(row).index("derived_supports") == list(row).index("supports") + 1


def test_gap_rounds_count_verified_facts_only(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_DERIVED_FINDINGS", "true")
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, DerivedOnlyWorld(gap_followups=True))
    assert rc == 0
    followups = [record for kid, record in _records(out).items() if kid.startswith("G")]
    assert followups and all(f["tag"] == "DERIVED" for record in followups for f in record["facts"])
    assert sum(len(record["facts"]) for record in followups) >= lr.GAP_MIN_NEW_VERIFIED
    # Three or more DERIVED follow-up facts are no new VERIFIED facts.
    assert "diminishing returns (0 new verified facts)" in meta["phases"]["gap"]["detail"]
    assert meta["kiqs"]["verified"] == 0 and meta["kiqs"]["derived"] == meta["kiqs"]["facts"]


def test_a_resumed_derived_fact_on_a_shell_page_is_unverified(tmp_path):
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    row = ledger.register("https://agency.gov/capacity", "Capacity statistics", "")
    fact = only(FINDING)
    fact["derivation"]["sid"] = row["sid"]
    verified = {"kiq": "K1", "text": "Capacity reached 37 GW [S1]", "sids": [row["sid"]], "tag": "VERIFIED",
                "verified_numbers": True}
    record = _record([fact, verified])
    engine = types.SimpleNamespace(stored_shells={row["sid"]: "reader_shell"}, ledger=ledger)
    lr._Engine._demote_shell_facts(engine, record)
    assert record["facts"][0] == {"kiq": "K1", "text": "Capacity grew about 185% [S12]", "sids": [12],
                                  "tag": "UNVERIFIED", "verified_numbers": None, "derivation_error": "unshown_source"}
    assert record["facts"][1]["tag"] == "REPORTED"
    kept = only(FINDING)
    lr._Engine._demote_shell_facts(types.SimpleNamespace(stored_shells={}, ledger=ledger), _record([kept]))
    assert kept["tag"] == "DERIVED"


def test_derived_facts_trace_the_published_numbers(tmp_path):
    engine = types.SimpleNamespace(records={"K1": _record(post(FINDING))}, plan=types.SimpleNamespace(scenarios=[]),
                                   page_numbers=lambda sid: frozenset(), ledger=types.SimpleNamespace(get={}.get))
    traced = lr._Engine._traced_numbers(engine, [], set())
    assert "185" in traced and "%185" in traced
    engine.records = {"K1": _record(post(FINDING, derivations=False))}
    assert "185" in lr._Engine._traced_numbers(engine, [], set())          # REPORTED, as before


# ================================================================== wiring

def test_knob_is_a_config_default_documented_and_forwarded_to_the_v3_child(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import check_env_drift as drift

    assert drift.config_defaults()["RESEARCH_DERIVED_FINDINGS"] == "false"
    assert "RESEARCH_DERIVED_FINDINGS" in drift.documented_env_vars()
    strict = subprocess.run([sys.executable, drift.__file__, "--strict"], capture_output=True, text=True,
                            timeout=60)
    assert strict.returncode == 0, strict.stdout
    assert ("RESEARCH_DERIVED_FINDINGS", "bool") in po.RESEARCH_CHILD_V3_KNOBS
    assert "RESEARCH_DERIVED_FINDINGS" in v3._ENV_EXACT
    for name, value in (("on", True), ("off", False)):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", "v3", raising=False)
        monkeypatch.setattr(po.Config, "RESEARCH_DERIVED_FINDINGS", value, raising=False)
        monkeypatch.setenv("RESEARCH_DERIVED_FINDINGS", "false" if value else "true")   # ambient env never decides
        child = _launch_capturing_child(monkeypatch, tmp_path / name, timeout=900)
        assert child["env"]["RESEARCH_DERIVED_FINDINGS"] == ("true" if value else "false")


def test_derived_numbers_is_deployed_with_the_engine():
    assert "derived_numbers.py" in po._DEPLOYED_BRIDGE_MODULES
    setup = (Path(__file__).resolve().parents[2] / "setup.sh").read_text(encoding="utf-8")
    loop = next(line.strip() for line in setup.splitlines() if line.strip().startswith("for _tool_mod in "))
    assert "derived_numbers.py" in loop[len("for _tool_mod in "):].split(";", 1)[0].split()


def test_the_bridge_module_imports_only_the_standard_library():
    source = (Path(dn.__file__)).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:from|import) ([\w.]+)", source, re.M))
    assert imported <= {"__future__", "ast", "keyword", "re", "unicodedata", "decimal", "typing"}
    # A derivation is plain JSON (the result a string): KIQ records round-trip it.
    fact = only(FINDING)
    assert json.loads(json.dumps(fact)) == fact
