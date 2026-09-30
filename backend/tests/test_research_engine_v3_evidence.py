"""RESEARCH-7: verbatim evidence-span contract for v3 findings.

RESEARCH_EVIDENCE_QUOTES (off | audit | enforce, default off):

* off — the KIQ task, ENGINE_CORE, the facts, the ledger rows and sources.json
  are exactly what they were;
* audit — each finding's EVIDENCE clause is split off and its quotes are
  located in the stored page / search text of the cited sources; facts record
  evidence, evidence_status, evidence_near_miss, claimed_tag and what enforce
  would do; no tag changes; meta.evidence and an [evidence] line per KIQ;
* enforce — a fact whose quotes are nowhere in what the agent was shown is
  UNVERIFIED (evidence_not_on_page) and a VERIFIED fact whose numbers lie
  outside its quoted passages is REPORTED (numbers_outside_evidence): the
  documented "40 sites" / "40 months" bare-number residual.

RESEARCH_EVIDENCE_SUPPORTS (default false) puts up to 3 located quotes per
source into sources.json supports ahead of REPORT-7's windows.  Offline: the
scripted model, injected search/fetch and real bridge of
``test_research_engine_v3``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import test_research_engine_v3 as v3
from test_orchestrator_research_wiring import _launch_capturing_child

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg
po = v3.po
es = lr.es

LEGACY_FACT_KEYS = {"kiq", "text", "sids", "tag", "verified_numbers", "verification", "missing_numbers"}
EVIDENCE_FACT_KEYS = {"claimed_tag", "evidence", "evidence_status", "evidence_near_miss"}
TEMPLATE_TAIL = ("Aim for 6 to 15 findings. Each finding must be specific and self-contained: a reader who sees "
                 "only that bullet must understand it.")

FILLER = "The survey method section describes sampling, weighting and the response rates of operators. "
PAGE = ("# Official statistics release\n\n"
        "Installed data-centre capacity reached 176 GW in 2023, up from 150 GW in 2022, according to the "
        "national energy agency's annual survey of operators.\n\n" + FILLER * 6 +
        "\n\nThe agency notes that grid connection queues exceed 40 months in several regions.")
TABLE_PAGE = ("Regional capacity survey.\n\nTable 1: Installed capacity by region (GW)\n\n"
              "| Region | Installed capacity in 2023 |\n|---|---|\n| North region | 44 GW installed |\n"
              + "".join(f"| Zone {zone} of the regional grid | not reported this year |\n" for zone in "ABCDEFGHIJ")
              + "| South region | 15 GW installed |\n\n" + FILLER * 5 + "Total 59 GW.")
QUOTE_176 = "Installed data-centre capacity reached 176 GW in 2023, up from 150 GW in 2022"
QUOTE_HEAD = "Installed data-centre capacity reached 176 GW in 2023"
QUOTE_QUEUES = "grid connection queues exceed 40 months in several regions"
FABRICATED = "The minister told parliament that the regulator had approved 150 GW of new connections in 2022"
SNIPPET = "Capacity statistics 2023: 176 GW installed; outlook note 1."
SNIPPET_QUOTE = "Capacity statistics 2023: 176 GW installed"
LONG_QUOTE = (FILLER * 4).strip()

ROWS = {
    1: {"sid": 1, "fetched": True, "title": "Official statistics release", "snippet": SNIPPET},
    2: {"sid": 2, "fetched": False, "title": "Analyst outlook for data-centre capacity in 2024",
        "snippet": "An analyst expects 12% annual demand growth through 2027 in the survey.",
        "snippets": ["An analyst expects 12% annual demand growth through 2027 in the survey.",
                     "Operators added 25 GW in the first half, the analyst estimates."]},
    3: {"sid": 3, "fetched": True, "title": "Regional survey", "snippet": ""},
    4: {"sid": 4, "fetched": True, "title": "Agency release", "snippet": ""},
}
NESTED_PAGE = ("In its release the agency said “installed capacity reached 176 GW” in 2023, a record for "
               "the operators it surveys.")
PAGES = {1: PAGE, 3: TABLE_PAGE, 4: NESTED_PAGE}


def page_numbers(sid):
    return lr.page_number_set(PAGES[sid]) if sid in PAGES else None


def post(notes: str, mode: str = "audit", **kwargs) -> list[dict]:
    return lr.postprocess_notes("K1", notes, ROWS.get, page_numbers, evidence_mode=mode,
                                page_text=PAGES.get, **kwargs)[1]["facts"]


def findings(*lines: str) -> str:
    return "\n".join(["## Findings", *lines, "## Conflicts", "## Open questions", "## Discovered"])


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ================================================================== parsing

def test_off_mode_ignores_the_new_arguments():
    """Off is the legacy postprocessing, whatever the clause, getters or keys."""
    notes = findings(f'- Installed capacity reached 176 GW in 2023 [S1] (VERIFIED) EVIDENCE: "{QUOTE_176}"',
                     f'- Operators run 40 sites across the region [S1] (VERIFIED) EVIDENCE: "{QUOTE_HEAD}"',
                     f'- Growth is 12% a year EVIDENCE: [S2] "{FABRICATED}" (REPORTED)')
    legacy = lr.postprocess_notes("K1", notes, ROWS.get, page_numbers)
    for mode in ("off", "", "bogus"):
        assert lr.postprocess_notes("K1", notes, ROWS.get, page_numbers, evidence_mode=mode, page_text=PAGES.get,
                                    row_text=lambda sid: ["unused"]) == legacy
    facts = legacy[1]["facts"]
    assert all(set(fact) <= LEGACY_FACT_KEYS for fact in facts)
    assert "EVIDENCE" in facts[0]["text"]                     # off never splits a clause


def test_audit_parses_spans_without_changing_tags_or_keeping_the_clause():
    notes = findings(
        f'- Installed capacity reached 176 GW in 2023 [S1] (VERIFIED) EVIDENCE: "{QUOTE_176}"',
        f'- Operators run 40 sites across the region [S1] (VERIFIED) EVIDENCE: "{QUOTE_HEAD}"',
        f'- Capacity rose to 150 GW in 2022 [S1] (VERIFIED) EVIDENCE: "{FABRICATED}"',
        "- The 2022 baseline was 150 GW of installed capacity [S1] (VERIFIED)",
        f'- An analyst expects 12% annual demand growth [S2] (REPORTED) EVIDENCE: “{ROWS[2]["snippet"][:-15]}”')
    off = post(notes, "off")
    audit = post(notes, "audit")
    assert [fact["tag"] for fact in audit] == [fact["tag"] for fact in off] == ["VERIFIED"] * 4 + ["REPORTED"]
    assert [fact["claimed_tag"] for fact in audit] == ["VERIFIED"] * 4 + ["REPORTED"]
    for fact in audit:
        assert "EVIDENCE" not in fact["text"] and '"' not in fact["text"]
        assert EVIDENCE_FACT_KEYS <= set(fact)
    assert audit[0]["text"] == "Installed capacity reached 176 GW in 2023 [S1]"
    assert audit[0]["evidence"] == [{"sid": 1, "quote": QUOTE_176, "basis": "exact", "start": PAGE.index(QUOTE_176),
                                     "end": PAGE.index(QUOTE_176) + len(QUOTE_176), "target": "page"}]
    assert [fact["evidence_status"] for fact in audit] == ["verified", "verified", "failed", "absent", "verified"]
    assert audit[4]["evidence"][0]["target"] == "snippet" and audit[4]["evidence"][0]["sid"] == 2
    # What enforce would do is recorded; no tag changed.
    assert audit[1]["evidence_verdict"] == "numbers_outside_evidence"
    assert audit[2]["evidence_verdict"] == "evidence_not_on_page"
    assert "evidence_verdict" not in audit[0] and "verification" not in audit[1]
    assert [fact.get("number_check") for fact in audit] == [None] * 4 + ["ok"]
    summary = lr.evidence_summary([{"evidence_contract": "audit:v1", "facts": audit}], "audit")
    assert summary == {
        "mode": "audit", "contract": "audit:v1", "facts": 5, "with_spans": 3,
        "located": {"exact": 3, "normalized": 0, "segmented": 0}, "failed": 1, "near_miss": 0,
        "demoted": {"numbers_outside_evidence": 1, "evidence_not_on_page": 1}, "absent": 1, "not_requested": 0,
        "claim_grounding": 0.6, "claimed_verified": {"facts": 4, "located": 2},
        "reported_numbers": {"checked": 1, "missing": 0, "not_checkable": 0}}


def test_enforce_keeps_a_verified_176_gw_fact_whose_span_contains_176():
    (fact,) = post(findings(f'- Installed capacity reached 176 GW in 2023 [S1] (VERIFIED) EVIDENCE: "{QUOTE_176}"'),
                   "enforce")
    assert fact["tag"] == "VERIFIED" and fact["evidence_status"] == "verified"
    (entry,) = fact["evidence"]
    window = es.evidence_window(PAGE, es.SpanMatch(entry["basis"], entry["start"], entry["end"]))
    assert "176" in window and all(token in lr.page_number_set(window) for token in lr.fact_number_tokens(fact["text"]))


def test_enforce_demotes_the_bare_number_residual():
    """"40 sites" is VERIFIED today because 40 is on the page ("40 months",
    far from the passage the finding quotes); enforce makes it REPORTED."""
    notes = findings(f'- Operators run 40 sites across the region [S1] (VERIFIED) EVIDENCE: "{QUOTE_HEAD}"')
    (legacy,) = post(notes, "off")
    assert legacy["tag"] == "VERIFIED" and legacy["verified_numbers"] is True     # the residual
    (fact,) = post(notes, "enforce")
    assert fact["tag"] == "REPORTED" and fact["claimed_tag"] == "VERIFIED"
    assert fact["verification"] == "numbers_outside_evidence" and fact["outside_evidence_numbers"] == ["40"]
    assert fact["number_check"] == "ok"                        # 40 is on the page: the audit agrees
    (audited,) = post(notes, "audit")
    assert audited["tag"] == "VERIFIED" and audited["evidence_verdict"] == "numbers_outside_evidence"
    # A passage that does contain the number keeps the fact VERIFIED.
    (kept,) = post(findings(f'- Queues exceed 40 months [S1] (VERIFIED) EVIDENCE: "{QUOTE_QUEUES}"'), "enforce")
    assert kept["tag"] == "VERIFIED" and "verification" not in kept


def test_enforce_turns_a_fabricated_span_into_unverified():
    notes = findings(f'- Capacity rose to 150 GW in 2022 [S1] (VERIFIED) EVIDENCE: "{FABRICATED}"',
                     f'- Growth is 12% a year [S2] (REPORTED) EVIDENCE: "{FABRICATED}"',
                     f'- Capacity doubled to 300 GW [S1] (VERIFIED) EVIDENCE: "{FABRICATED}"')
    verified, reported, missing = post(notes, "enforce")
    assert verified["tag"] == "UNVERIFIED" and verified["verification"] == "evidence_not_on_page"
    assert verified["evidence_status"] == "failed" and verified["evidence"] == []
    assert reported["tag"] == "UNVERIFIED" and reported["verification"] == "evidence_not_on_page"
    # Already UNVERIFIED by the page-number rule: kept as it was, not counted as an evidence demotion.
    assert missing["tag"] == "UNVERIFIED" and missing["missing_numbers"] == ["300"]
    assert "evidence_verdict" not in missing and "verification" not in missing


def test_a_paraphrase_is_a_near_miss():
    paraphrase = "Installed data-centre capacity reached a record of about one hundred seventy-six gigawatts"
    (fact,) = post(findings(f'- Capacity reached 176 GW [S1] (VERIFIED) EVIDENCE: "{paraphrase}"'), "audit")
    assert fact["evidence_status"] == "failed" and fact["evidence_near_miss"] is True


def test_verified_without_a_clause_stays_verified_with_status_absent():
    notes = findings("- The 2022 baseline was 150 GW of installed capacity [S1] (VERIFIED)",
                     "- Capacity reached 176 GW in 2023 [S1] (VERIFIED) EVIDENCE: see the agency release")
    for fact in post(notes, "enforce"):
        assert fact["tag"] == "VERIFIED" and fact["evidence_status"] == "absent" and fact["evidence"] == []
        assert "verification" not in fact and "evidence_verdict" not in fact


def test_a_tag_or_marker_written_after_the_clause_is_still_parsed():
    notes = findings(f'- Installed capacity was 176 GW in 2023 EVIDENCE: [S1] "{QUOTE_HEAD}" (VERIFIED)',
                     f'- Statistics put installed capacity at 176 GW **EVIDENCE:** [S2] "{FABRICATED}" '
                     f'[S1] "{SNIPPET_QUOTE}" (REPORTED)',
                     f'- 数据中心装机容量为176吉瓦 [S1] (已核实) 证据：「{QUOTE_HEAD}」')
    first, second, chinese = post(notes, "enforce")
    assert first["sids"] == [1] and first["tag"] == first["claimed_tag"] == "VERIFIED"
    assert first["text"] == "Installed capacity was 176 GW in 2023 [S1]"
    assert first["evidence"][0]["sid"] == 1 and first["evidence"][0]["target"] == "page"
    # Each quote is looked for in the source its marker binds it to only.
    assert second["sids"] == [2, 1] and second["claimed_tag"] == "REPORTED"
    assert second["text"] == "Statistics put installed capacity at 176 GW [S2][S1]"
    assert [(e["sid"], e["target"]) for e in second["evidence"]] == [(1, "snippet")]
    assert second["tag"] == "REPORTED" and second["evidence_status"] == "verified"
    assert chinese["tag"] == "VERIFIED" and chinese["evidence"][0]["basis"] == "exact"
    assert chinese["text"] == "数据中心装机容量为176吉瓦 [S1]"


def test_nested_quotes_and_a_tag_inside_the_quote_marks_do_not_fail_a_real_passage():
    notes = findings('- Capacity reached 176 GW in 2023 [S4] (VERIFIED) EVIDENCE: "the agency said "installed '
                     'capacity reached 176 GW" in 2023, a record"',
                     f'- Capacity reached 176 GW in 2023 [S1] EVIDENCE: "{QUOTE_HEAD} (VERIFIED)"')
    nested, tagged = post(notes, "enforce")
    assert nested["tag"] == "VERIFIED" and nested["evidence_status"] == "verified"
    assert nested["evidence"][0]["quote"] == 'the agency said "installed capacity reached 176 GW" in 2023, a record'
    assert nested["evidence"][0]["basis"] == "normalized"
    assert tagged["tag"] == tagged["claimed_tag"] == "VERIFIED"
    assert tagged["evidence"][0]["quote"] == QUOTE_HEAD and tagged["evidence"][0]["basis"] == "exact"
    # Two separate quotes that are both invented are not rescued by the fallback.
    (invented,) = post(findings(f'- Capacity reached 176 GW [S1] (VERIFIED) EVIDENCE: "{FABRICATED}" "{FABRICATED}!"'),
                       "enforce")
    assert invented["tag"] == "UNVERIFIED" and invented["evidence_status"] == "failed"


def test_quotes_are_located_in_every_snippet_sighting_and_the_title():
    notes = findings("- Operators added 25 GW in the first half [S2] (REPORTED) EVIDENCE: "
                     '"Operators added 25 GW in the first half, the analyst estimates"',
                     '- The outlook covers 2024 [S2] (REPORTED) EVIDENCE: "Analyst outlook for data-centre capacity"')
    sighting, title = post(notes, "audit")
    assert sighting["evidence"][0]["target"] == "snippet" and title["evidence"][0]["target"] == "snippet"
    # A quoted table row is checked against the whole table: the South row is
    # far outside the row's own window, yet its 15 GW is inside the evidence.
    notes = findings('- The North region had 44 GW and the South region 15 GW [S3] (VERIFIED) EVIDENCE: '
                     '"| North region | 44 GW installed |"')
    (row,) = post(notes, "enforce")
    entry = row["evidence"][0]
    assert TABLE_PAGE.index("| South region") - entry["end"] > 200
    assert row["tag"] == "VERIFIED" and entry["target"] == "page" and "verification" not in row


def test_the_reported_number_audit_skips_years_exponents_and_bibliographic_ids():
    notes = findings(
        "- The survey (vol. 31, pp. 118-126, No. 4, article 5521, doi:10.1000/xyz123) in 2021 and on 14 March "
        "found 176 GW, about 10^9 kWh or 10⁹ W [S1] (REPORTED)",
        "- An analyst expects 12% growth and 9,999 new sites [S2] (REPORTED)",
        "- The programme started in 2019 [S2] (REPORTED)",
        "- Capacity rose to 150 GW in 2022 [S1] (VERIFIED)")
    for mode in ("audit", "enforce"):
        excluded, missing, years, verified = post(notes, mode)
        assert excluded["number_check"] == "ok" and "number_check_missing" not in excluded
        assert missing["number_check"] == "missing" and missing["number_check_missing"] == ["9999"]
        assert years["number_check"] == "not_checkable"
        assert "number_check" not in verified
        assert [f["tag"] for f in (excluded, missing, years, verified)] == ["REPORTED"] * 3 + ["VERIFIED"]


def test_evidence_summary_counts_other_contracts_as_not_requested():
    facts = post(findings(f'- Capacity reached 176 GW in 2023 [S1] (VERIFIED) EVIDENCE: "{QUOTE_176}"'), "enforce")
    records = [{"evidence_contract": "enforce:v1", "facts": facts},
               {"facts": [{"tag": "VERIFIED"}, {"tag": "REPORTED"}]},
               {"evidence_contract": "audit:v1", "facts": [{"tag": "VERIFIED"}]}]
    summary = lr.evidence_summary(records, "enforce")
    assert summary["facts"] == 1 and summary["not_requested"] == 3 and summary["claim_grounding"] == 1.0
    assert lr.evidence_summary([], "audit")["claim_grounding"] is None


def test_gap_counts_the_claimed_tag_in_enforce_mode():
    demoted = {"tag": "UNVERIFIED", "claimed_tag": "VERIFIED"}
    legacy = {"tag": "VERIFIED"}
    assert lr._gap_counts_verified(demoted, enforce=True) is True
    assert lr._gap_counts_verified(demoted, enforce=False) is False
    assert lr._gap_counts_verified(legacy, enforce=True) is True
    assert lr._gap_counts_verified({"tag": "REPORTED", "claimed_tag": "REPORTED"}, enforce=True) is False


# ================================================================== ledger

def test_the_ledger_keeps_distinct_snippets_only_when_asked(tmp_path):
    def sightings(ledger):
        first = ledger.register("https://agency.gov/r", "Agency report", "Capacity reached 176 GW in 2023.")
        for text in ("Capacity reached 176 GW in 2023.", "Second: 150 GW in 2022.", "Third: 12% growth.",
                     "Fourth: 40 months.", "Fifth: dropped.", "x" * 900):
            ledger.register("https://agency.gov/r", "Other title", text)
        return first, ledger.get(1)

    first, row = sightings(rg.SourceLedger(tmp_path / "off.json"))
    assert row == {"sid": 1, "url": "https://agency.gov/r", "canonical": rg.canonical_url("https://agency.gov/r"),
                   "title": "Agency report", "domain": "agency.gov", "tier": "S3", "via": "search",
                   "fetched": False, "content_sha256": None, "chars": 0, "page_path": None,
                   "snippet": "Capacity reached 176 GW in 2023.", "first_seen_by": ""}
    assert first == row

    ledger = rg.SourceLedger(tmp_path / "on.json")
    ledger.keep_snippets = True
    first, row = sightings(ledger)
    assert first["snippets"] == ["Capacity reached 176 GW in 2023."]      # a copy handed out never changes
    assert row["snippet"] == "Capacity reached 176 GW in 2023."
    assert row["snippets"] == ["Capacity reached 176 GW in 2023.", "Second: 150 GW in 2022.", "Third: 12% growth.",
                               "Fourth: 40 months."]
    ledger.flush()
    assert rg.SourceLedger(tmp_path / "on.json").get(1)["snippets"] == row["snippets"]
    long_row = ledger.register("https://agency.gov/long", "", "y" * 900)
    assert long_row["snippets"] == [long_row["snippet"]] and len(long_row["snippet"]) <= 500


# ================================================================== engine runs

def _sids(tool_results):
    fetched = next((int(m.group(1)) for r in tool_results
                    for m in [re.match(r"\[S(\d+)\].*(?:excerpt|full page)", r)] if m), None)
    searched = [int(s) for r in tool_results for s in re.findall(r"^\[S(\d+)\]", r, re.M)]
    other = next((s for s in searched if s != fetched), fetched or 1)
    return fetched or other, other


def long_page(url: str) -> str:
    return PAGE


class EvidenceWorld(v3.World):
    """Findings with EVIDENCE clauses: a quote on the page, the residual, a
    fabrication, no clause, and a snippet quote bound after the clause."""

    def notes(self, tool_results) -> str:
        cite, other = _sids(tool_results)
        return findings(
            f'- Installed capacity reached 176 GW in 2023 per the agency survey [S{cite}] (VERIFIED) '
            f'EVIDENCE: "{QUOTE_176}"',
            f'- Operators run 40 sites across the region [S{cite}] (VERIFIED) EVIDENCE: "{QUOTE_HEAD}"',
            f'- Capacity rose to 150 GW in 2022 [S{cite}] (VERIFIED) EVIDENCE: "{FABRICATED}"',
            f"- The 2022 baseline was 150 GW of installed capacity [S{cite}] (VERIFIED)",
            f'- Statistics put installed capacity at 176 GW EVIDENCE: [S{other}] "{SNIPPET_QUOTE}" (REPORTED)')


class FabricatingWorld(v3.World):
    """Every VERIFIED finding quotes an invented passage (the numbers are on
    the page, so only the evidence rule demotes them)."""

    def notes(self, tool_results) -> str:
        cite, _ = _sids(tool_results)
        return findings(*(f'- {text} [S{cite}] (VERIFIED) EVIDENCE: "{FABRICATED} ({n})"'
                          for n, text in enumerate(("Installed capacity reached 176 GW in 2023",
                                                    "Capacity was 150 GW in 2022",
                                                    "Queues exceed 40 months in several regions"), 1)))


class SupportsWorld(v3.World):
    """Four page quotes and a snippet quote (written first) on each fetched source."""

    def notes(self, tool_results) -> str:
        cite, _ = _sids(tool_results)
        return findings(
            f'- Statistics put installed capacity at 176 GW [S{cite}] (REPORTED) EVIDENCE: "{SNIPPET_QUOTE}"',
            f'- Installed capacity reached 176 GW in 2023 [S{cite}] (VERIFIED) EVIDENCE: "{QUOTE_HEAD}" '
            '"up from 150 GW in 2022, according to the national energy agency"',
            f'- The survey method is documented [S{cite}] (REPORTED) EVIDENCE: "{LONG_QUOTE}" "{QUOTE_QUEUES}"')


def _records(out: Path) -> dict[str, dict]:
    return {path.stem: _load(path) for path in sorted((out / "v3" / "kiq").glob("*.json"))}


def _kiq_tasks(model) -> set[str]:
    return {call["messages"][2][1] for call in v3.calls_of(model, "agent") if len(call["messages"]) == 3}


def _systems(model) -> set[str]:
    return {call["messages"][0][1] for call in model.calls}


def _tags(records: dict[str, dict]) -> dict[str, list[str]]:
    return {kid: [fact["tag"] for fact in record["facts"]] for kid, record in records.items()}


def test_off_mode_is_byte_identical(tmp_path, bridge, monkeypatch):
    """Off (default, explicit, or an unknown value; the supports knob alone
    does nothing): the KIQ task is exactly the template, ENGINE_CORE is the
    system prompt, facts have only the legacy keys, ledger rows no snippets,
    supports [] before REPORT-7's windows, and nothing new is written.  One
    worker makes the runs deterministic, so every prompt and artifact of the
    three runs is compared byte for byte."""
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    built: list[bytes] = []
    real_rows = lr._Engine._source_rows

    def source_rows(self, order):
        rows = real_rows(self, order)
        built.append(json.dumps(rows, ensure_ascii=False).encode("utf-8"))
        return rows

    monkeypatch.setattr(lr._Engine, "_source_rows", source_rows)
    outs = []
    for name, env in (("default", {}), ("off", {"RESEARCH_EVIDENCE_QUOTES": "off", "RESEARCH_EVIDENCE_SUPPORTS": "true"}),
                      ("bogus", {"RESEARCH_EVIDENCE_QUOTES": "strict"})):
        for key in ("RESEARCH_EVIDENCE_QUOTES", "RESEARCH_EVIDENCE_SUPPORTS"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, EvidenceWorld(), out_dir=tmp_path / name,
                                                   fetch=long_page)
        assert rc == 0 and meta["status"] == "completed"
        tasks = _kiq_tasks(model)
        assert tasks and all(task.endswith(TEMPLATE_TAIL) and lr._KIQ_EVIDENCE_RULE not in task for task in tasks)
        assert _systems(model) == {lr.ENGINE_CORE}
        records = _records(out)
        assert records and all("evidence_contract" not in record for record in records.values())
        assert all(set(fact) <= LEGACY_FACT_KEYS for record in records.values() for fact in record["facts"])
        assert all("snippets" not in row for row in _load(out / "v3" / "sources_ledger.json"))
        assert all(row["supports"] == [] for row in json.loads(built[-1]))
        assert "evidence" not in meta and "evidence" not in _load(out / "meta.json") and not plog.of("evidence")
        warned = [m for m in plog.of("warn") if "RESEARCH_EVIDENCE_QUOTES" in m]
        assert bool(warned) == (name == "bogus")
        outs.append((out, [call["messages"] for call in model.calls]))
    first, first_calls = outs[0]
    for out, calls in outs[1:]:
        assert calls == first_calls
        for name in ("sources.json", "quantitative.json", "research_report.md", "v3/sources_ledger.json"):
            assert (out / name).read_bytes() == (first / name).read_bytes(), name
        assert [record["facts"] for record in _records(out).values()] == \
            [record["facts"] for record in _records(first).values()]


def test_audit_mode_records_evidence_and_changes_no_tag(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")   # deterministic runs: the two runs' prompts compare
    rc, _, _, off_model, off_out = v3.run_engine(tmp_path, bridge, EvidenceWorld(), out_dir=tmp_path / "off",
                                                 fetch=long_page)
    assert rc == 0
    monkeypatch.setenv("RESEARCH_EVIDENCE_QUOTES", "audit")
    rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, EvidenceWorld(), out_dir=tmp_path / "audit",
                                               fetch=long_page)
    assert rc == 0 and meta["status"] == "completed"
    tasks = _kiq_tasks(model)
    assert tasks and all(task.endswith(TEMPLATE_TAIL + "\n" + lr._KIQ_EVIDENCE_RULE) for task in tasks)
    assert {task[:-len(lr._KIQ_EVIDENCE_RULE) - 1] for task in tasks} == _kiq_tasks(off_model)
    assert _systems(model) == _systems(off_model) == {lr.ENGINE_CORE}   # the cached system prompt is unchanged
    records = _records(out)
    assert _tags(records) == _tags(_records(off_out))
    n = len(records)
    for record in records.values():
        assert record["evidence_contract"] == "audit:v1"
        assert [f["evidence_status"] for f in record["facts"]] == ["verified", "verified", "failed", "absent",
                                                                   "verified"]
        assert all("EVIDENCE" not in f["text"] for f in record["facts"])
    evidence = meta["evidence"]
    assert evidence == _load(out / "meta.json")["evidence"]
    assert evidence["mode"] == "audit" and evidence["facts"] == 5 * n and evidence["with_spans"] == 3 * n
    assert evidence["located"] == {"exact": 3 * n, "normalized": 0, "segmented": 0}
    assert evidence["demoted"] == {"numbers_outside_evidence": n, "evidence_not_on_page": n}
    assert (evidence["failed"], evidence["absent"], evidence["not_requested"]) == (n, n, 0)
    assert evidence["claim_grounding"] == 0.6 and evidence["claimed_verified"] == {"facts": 4 * n, "located": 2 * n}
    assert evidence["reported_numbers"] == {"checked": n, "missing": 0, "not_checkable": 0}
    lines = plog.of("evidence")
    assert len(lines) == n and all(" audit facts=5 with_spans=3 failed=1 absent=1" in line for line in lines)
    assert not any(line.startswith("research:v3:") for line in lines)
    assert any(row.get("snippets") for row in _load(out / "v3" / "sources_ledger.json"))


def test_enforce_mode_demotes_and_reports(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_EVIDENCE_QUOTES", "enforce")
    rc, meta, plog, _, out = v3.run_engine(tmp_path, bridge, EvidenceWorld(), fetch=long_page)
    assert rc == 0 and meta["status"] == "completed"
    records = _records(out)
    for record in records.values():
        assert record["evidence_contract"] == "enforce:v1"
        assert [f["tag"] for f in record["facts"]] == ["VERIFIED", "REPORTED", "UNVERIFIED", "VERIFIED", "REPORTED"]
        assert [f.get("verification") for f in record["facts"]][1:3] == ["numbers_outside_evidence",
                                                                        "evidence_not_on_page"]
        # Every VERIFIED fact with numbers and a clause has a page span whose window holds them.
        for fact in record["facts"]:
            if fact["tag"] == "VERIFIED" and fact["evidence_status"] == "verified":
                entry = next(e for e in fact["evidence"] if e["target"] == "page")
                window = es.evidence_window(PAGE, es.SpanMatch(entry["basis"], entry["start"], entry["end"]))
                assert not lr._missing_numbers(fact["text"], lr.fact_number_tokens(fact["text"]),
                                               lr.page_number_set(window))
    n = len(records)
    assert meta["evidence"]["mode"] == "enforce"
    assert meta["evidence"]["demoted"] == {"numbers_outside_evidence": n, "evidence_not_on_page": n}
    assert meta["kiqs"]["verified"] == 2 * n
    assert all(" enforce " in line and "demoted=2" in line for line in plog.of("evidence"))
    # Half of the claimed-VERIFIED findings have a located quote: no degradation event.
    assert not any("evidence quotes" in event for event in meta["research_quality"].get("degradation") or [])


def test_enforce_gap_rounds_count_the_claimed_tag_and_low_located_share_is_an_event(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_EVIDENCE_QUOTES", "enforce")
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, FabricatingWorld(gap_followups=True), fetch=long_page)
    assert rc == 0
    records = _records(out)
    followups = [record for kid, record in records.items() if kid.startswith("G")]
    assert followups and all(f["tag"] == "UNVERIFIED" and f["claimed_tag"] == "VERIFIED"
                             for record in followups for f in record["facts"])
    # Three claimed-VERIFIED findings per follow-up: the round is no "diminishing returns" stop.
    assert "diminishing returns" not in meta["phases"]["gap"]["detail"]
    assert meta["phases"]["gap"]["status"] == "done"
    events = meta["research_quality"]["degradation"]
    total = sum(len(record["facts"]) for record in records.values())
    assert f"evidence quotes located for only 0 of {total} findings the research agents tagged VERIFIED" in events


def test_resuming_off_records_under_enforce_keeps_tags_and_calls_no_model(tmp_path, bridge, monkeypatch):
    out = tmp_path / "out"
    rc, _, _, _, _ = v3.run_engine(tmp_path, bridge, EvidenceWorld(), out_dir=out, fetch=long_page)
    assert rc == 0
    before = {path.name: path.read_bytes() for path in (out / "v3" / "kiq").glob("*.json")}
    monkeypatch.setenv("RESEARCH_EVIDENCE_QUOTES", "enforce")
    silent = v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    rc, meta, plog, model, _ = v3.run_engine(tmp_path, bridge, EvidenceWorld(), out_dir=out, model=silent,
                                             fetch=long_page)
    assert rc == 0 and model.calls == [] and meta["status"] == "completed"
    assert {path.name: path.read_bytes() for path in (out / "v3" / "kiq").glob("*.json")} == before
    records = _records(out)
    assert all(fact["tag"] in ("VERIFIED", "UNVERIFIED", "REPORTED") and "claimed_tag" not in fact
               for record in records.values() for fact in record["facts"])
    total = sum(len(record["facts"]) for record in records.values())
    assert meta["evidence"]["not_requested"] == total and meta["evidence"]["facts"] == 0
    assert meta["evidence"]["demoted"] == {"numbers_outside_evidence": 0, "evidence_not_on_page": 0}
    assert not plog.of("evidence")
    assert not any("evidence quotes" in e for e in meta["research_quality"].get("degradation") or [])


def test_supports_flag_puts_located_quotes_into_sources_json(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")   # deterministic runs: the two runs' sources compare
    monkeypatch.setenv("RESEARCH_EVIDENCE_QUOTES", "audit")
    rc, _, _, _, plain = v3.run_engine(tmp_path, bridge, SupportsWorld(), out_dir=tmp_path / "plain",
                                       fetch=long_page)
    assert rc == 0
    monkeypatch.setenv("RESEARCH_EVIDENCE_SUPPORTS", "true")
    rc, _, _, _, out = v3.run_engine(tmp_path, bridge, SupportsWorld(), out_dir=tmp_path / "supports",
                                     fetch=long_page)
    assert rc == 0
    ledger = {row["sid"]: row["url"] for row in _load(out / "v3" / "sources_ledger.json")}
    quoted = {ledger[e["sid"]] for record in _records(out).values() for f in record["facts"]
              for e in f["evidence"] if e["target"] == "page"}
    sources = _load(out / "sources.json")
    expected = [QUOTE_HEAD, "up from 150 GW in 2022, according to the national energy agency",
                lr._collapse(lr._collapse(LONG_QUOTE, lr.EVIDENCE_QUOTE_CHARS), 280)]
    plain_rows = {row["url"]: row for row in _load(plain / "sources.json")}
    assert [row["url"] for row in sources] == list(plain_rows)
    checked = 0
    for row in sources:
        base = plain_rows[row["url"]]
        # Only supports changed.
        assert {k: v for k, v in row.items() if k != "supports"} == {k: v for k, v in base.items() if k != "supports"}
        if row["url"] not in quoted:
            assert row["supports"] == base["supports"]
            continue
        checked += 1
        # <= 3 located page quotes (<= 280 chars) first, then REPORT-7's windows.
        assert len(base["supports"]) <= lr.EVIDENCE_WINDOWS_PER_SOURCE - 3
        assert row["supports"] == expected + base["supports"]
        assert all(len(span) <= 280 for span in expected) and len(LONG_QUOTE) > 280
        assert SNIPPET_QUOTE not in row["supports"] and QUOTE_QUEUES not in row["supports"]
    assert checked


def test_an_evidence_check_failure_degrades_to_the_legacy_notes(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_EVIDENCE_QUOTES", "enforce")

    def broken(*args, **kwargs):
        raise RuntimeError("matcher exploded")

    monkeypatch.setattr(lr, "_apply_evidence", broken)
    rc, meta, plog, _, out = v3.run_engine(tmp_path, bridge, EvidenceWorld(), fetch=long_page)
    assert rc == 0 and meta["status"] == "completed"
    records = _records(out)
    assert records and all("evidence_contract" not in record for record in records.values())
    assert all(set(f) <= LEGACY_FACT_KEYS for record in records.values() for f in record["facts"])
    assert meta["evidence"]["not_requested"] == sum(len(r["facts"]) for r in records.values())
    assert any("evidence check failed (RuntimeError: matcher exploded)" in m for m in plog.of("warn"))
    assert any(e.get("helper") == "evidence_quotes" for e in meta["analytics_errors"])


# ================================================================== wiring

def test_knobs_are_config_defaults_documented_and_forwarded_to_the_v3_child(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import check_env_drift as drift

    defaults = drift.config_defaults()
    assert defaults["RESEARCH_EVIDENCE_QUOTES"] == "off" and defaults["RESEARCH_EVIDENCE_SUPPORTS"] == "false"
    assert {"RESEARCH_EVIDENCE_QUOTES", "RESEARCH_EVIDENCE_SUPPORTS"} <= drift.documented_env_vars()
    strict = subprocess.run([sys.executable, drift.__file__, "--strict"], capture_output=True, text=True,
                            timeout=60)
    assert strict.returncode == 0, strict.stdout
    assert ("RESEARCH_EVIDENCE_QUOTES", "str") in po.RESEARCH_CHILD_V3_KNOBS
    assert ("RESEARCH_EVIDENCE_SUPPORTS", "bool") in po.RESEARCH_CHILD_V3_KNOBS
    assert "RESEARCH_EVIDENCE_QUOTES" in v3._ENV_EXACT and "RESEARCH_EVIDENCE_SUPPORTS" in v3._ENV_EXACT
    for name, quotes, supports in (("audit", "audit", True), ("off", "off", False)):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", "v3", raising=False)
        monkeypatch.setattr(po.Config, "RESEARCH_EVIDENCE_QUOTES", quotes, raising=False)
        monkeypatch.setattr(po.Config, "RESEARCH_EVIDENCE_SUPPORTS", supports, raising=False)
        monkeypatch.setenv("RESEARCH_EVIDENCE_QUOTES", "enforce")                   # ambient env never decides
        monkeypatch.setenv("RESEARCH_EVIDENCE_SUPPORTS", "false" if supports else "true")
        child = _launch_capturing_child(monkeypatch, tmp_path / name, timeout=900)
        assert child["env"]["RESEARCH_EVIDENCE_QUOTES"] == quotes
        assert child["env"]["RESEARCH_EVIDENCE_SUPPORTS"] == ("true" if supports else "false")


def test_evidence_spans_is_deployed_with_the_engine():
    assert "evidence_spans.py" in po._DEPLOYED_BRIDGE_MODULES
    setup = (Path(__file__).resolve().parents[2] / "setup.sh").read_text(encoding="utf-8")
    loop = next(line.strip() for line in setup.splitlines() if line.strip().startswith("for _tool_mod in "))
    assert "evidence_spans.py" in loop[len("for _tool_mod in "):].split(";", 1)[0].split()
