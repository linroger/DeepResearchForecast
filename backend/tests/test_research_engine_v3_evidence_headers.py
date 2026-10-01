"""RESEARCH-10: per-KIQ evidence count headers, sufficiency labels and fair
deterministic digest truncation in the v3 research engine.

* RESEARCH_EVIDENCE_HEADERS (default off): each KIQ block of the writers'
  evidence digest opens with the engine's count of its evidence and a
  sufficiency label (``evidence_profile``); a legend opens the digest, the gap
  review's coverage matrix gains fetched/domains/sufficiency, the section
  rules gain one thin-evidence line, meta.kiqs gains evidence/sufficiency and
  an insufficient-majority degradation event fires.
* RESEARCH_TRUNCATION_FAIRNESS (default off): the scout digest is shared
  fairly between the scout queries and cut only between results, and an
  over-cap digest block drops its least KIQ-relevant equal-priority line first.

Both off: digest, scout digest, coverage matrix and section task are
byte-identical.  Offline: the scripted model and real bridge of
``test_research_engine_v3``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

import test_research_engine_v3 as v3
from test_orchestrator_research_wiring import _launch_capturing_child

_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
po = v3.po

KNOBS = ("RESEARCH_EVIDENCE_HEADERS", "RESEARCH_TRUNCATION_FAIRNESS")
HEADER_RE = re.compile(
    r"^Evidence \(engine count\): \d+ sourced findings \(\d+ VERIFIED, \d+ REPORTED, \d+ UNVERIFIED"
    r"(?:, \d+ DERIVED)?\) from \d+ sources \(\d+ fetched, \d+ snippet-only; \d+ domains\); "
    r"sufficiency: (?:insufficient|thin|adequate) \([^\n]+\)(?:; \d+ lines omitted for length)?$")


class _Ledger:
    def __init__(self, rows):
        self.rows = rows

    def get(self, sid):
        return self.rows.get(int(sid))


LEDGER = _Ledger({1: {"title": "T1", "domain": "a.org", "tier": "S1", "fetched": True},
                  2: {"title": "T2", "domain": "b.org", "tier": "S2", "fetched": True},
                  3: {"title": "T3", "domain": "a.org", "tier": "S3", "fetched": False},
                  4: {"title": "T4", "domain": "A.org", "tier": "S1", "fetched": True}})


def _fact(text, tag="VERIFIED"):
    return {"text": text, "tag": tag}


ADEQUATE = [_fact("capacity 176 GW [S1]"), _fact("growth 12% [S2]"), _fact("queue 40 months [S1]", "REPORTED")]


def _record(facts, **extra):
    return {"id": "K1", "question": "Will data-centre capacity exceed 250 GW?", "facts": facts, **extra}


def _set_knobs(monkeypatch, *, headers=False, fairness=False):
    monkeypatch.setenv("RESEARCH_EVIDENCE_HEADERS", "true" if headers else "false")
    monkeypatch.setenv("RESEARCH_TRUNCATION_FAIRNESS", "true" if fairness else "false")


# =============================================================== evidence_profile

@pytest.mark.parametrize("facts, extra, label, reason", [
    (ADEQUATE, {}, "adequate", "at least 3 sourced findings"),
    (ADEQUATE, {"stats": {"fallback": "content_filter"}}, "insufficient",
     "deterministic fallback notes: content_filter"),
    (ADEQUATE[:2], {}, "insufficient", "fewer than 3 sourced findings"),
    ([_fact("a [S3]"), _fact("b [S3]"), _fact("c [S3]")], {}, "insufficient", "no fetched source"),
    ([_fact("a [S1]"), _fact("b [S2]", "REPORTED"), _fact("c [S2]", "UNVERIFIED")], {}, "thin",
     "fewer than 2 VERIFIED findings"),
    ([_fact("a [S1]"), _fact("b [S3]"), _fact("c [S1]")], {}, "thin", "fewer than 2 fetched sources"),
    ([_fact("a [S1]"), _fact("b [S4]"), _fact("c [S1]")], {}, "thin", "fewer than 2 domains"),
])
def test_evidence_profile_sufficiency_table(facts, extra, label, reason):
    profile = lr.evidence_profile(_record(facts, **extra), LEDGER.get)
    assert profile["sufficiency"] == label
    assert reason in profile["reason"]


def test_evidence_profile_counts_only_sourced_findings_and_shows_derived_when_present():
    record = _record([*ADEQUATE, _fact("no marker at all"), _fact("ratio 1.5 [S2]", "DERIVED"),
                      _fact("unknown tag [S3]", "SPECULATIVE")],
                     conflicts=["A vs B [S1][S2]"], open_questions=["why?", "when?"])
    profile = lr.evidence_profile(record, LEDGER.get)
    assert profile == {"sourced_findings": 5, "verified": 2, "reported": 2, "unverified": 0, "derived": 1,
                       "sources": 3, "fetched": 2, "snippet_only": 1, "domains": 2, "conflicts": 1,
                       "open_questions": 2, "fallback": None, "sufficiency": "adequate",
                       "reason": profile["reason"]}
    assert "derived" not in lr.evidence_profile(_record(ADEQUATE), LEDGER.get)
    empty = lr.evidence_profile({"facts": "junk", "stats": "junk"}, LEDGER.get)
    assert empty["sourced_findings"] == 0 and empty["sufficiency"] == "insufficient"


def test_evidence_profile_counts_only_admissible_sources_when_walled():
    record = _record([_fact("a [S1]"), _fact("b [S2]"), _fact("c [S1][S2]", "REPORTED")])
    walled = lr.evidence_profile(record, LEDGER.get, admissible=lambda sid: sid == 1)
    assert walled["sources"] == 1 and walled["fetched"] == 1 and walled["domains"] == 1
    assert walled["sourced_findings"] == 2      # the [S2]-only line is walled off entirely
    assert lr.evidence_profile(record, LEDGER.get)["sources"] == 2


# =============================================================== digest

def test_digest_header_line_is_the_pinned_second_line_and_legend_opens_the_digest():
    text, dropped = lr.build_digest([_record(ADEQUATE)], LEDGER.get, 5000, "English", evidence_headers=True)
    assert dropped == 0
    body = text.split("EVIDENCE DIGEST\n\n", 1)[1]
    assert body.startswith(lr.EVIDENCE_HEADER_LEGEND + "\n\n### K1")
    block = body.split("### K1", 1)[1].splitlines()
    assert block[1] == ("Evidence (engine count): 3 sourced findings (2 VERIFIED, 1 REPORTED, 0 UNVERIFIED) "
                        "from 2 sources (2 fetched, 0 snippet-only; 2 domains); sufficiency: adequate "
                        "(at least 3 sourced findings, 2 VERIFIED, 2 fetched sources and 2 domains)")
    assert HEADER_RE.match(block[1]) and block[2] == "Findings:"
    index = text.split("SOURCE INDEX\n", 1)[1]
    plain, _ = lr.build_digest([_record(ADEQUATE)], LEDGER.get, 5000, "English")
    assert index == plain.split("SOURCE INDEX\n", 1)[1]        # the header cites nothing


def test_header_counts_are_pre_drop_and_the_block_stays_within_its_cap():
    facts = [_fact(f"finding number {i} " + "x" * 120 + " [S1]", "REPORTED") for i in range(20)]
    facts += [_fact("verified one [S2]"), _fact("verified two [S1]")]
    record = _record(facts)
    cap = 1200
    block, lost = lr._kiq_digest_block(record, cap, "English", ledger_get=LEDGER.get, headers=True)
    assert lost > 0
    line = block.splitlines()[1]
    assert line.startswith("Evidence (engine count): 22 sourced findings (2 VERIFIED, 20 REPORTED, 0 UNVERIFIED)")
    assert line.endswith(f"; {lost} lines omitted for length") and HEADER_RE.match(line)
    header_len = len(block.splitlines()[0])
    kept_lines = [ln for ln in block.splitlines()[3:] if ln.startswith("- ")]
    assert header_len + 60 + len(line) + 1 + sum(len(ln) + 1 for ln in kept_lines) <= cap
    with pytest.raises(ValueError):
        lr._kiq_digest_block(record, cap, "English", headers=True)


def test_headers_off_is_the_plain_digest():
    records = [_record(ADEQUATE), {"id": "K2", "question": "two", "facts": [_fact("x [S3]", "REPORTED")]}]
    plain = lr.build_digest(records, LEDGER.get, 3000, "English")
    assert lr.build_digest(records, LEDGER.get, 3000, "English", evidence_headers=False,
                           relevance_drop=False) == plain
    assert "Evidence (engine count)" not in plain[0] and lr.EVIDENCE_HEADER_LEGEND not in plain[0]


def test_relevance_drop_removes_the_least_relevant_equal_priority_line_first():
    question = "Will grid connection queues delay data-centre capacity?"
    relevant = _fact("grid connection queues delay capacity additions in several regions [S1]", "REPORTED")
    unrelated = _fact("the operator changed its logo and moved headquarters to another city [S2]", "REPORTED")
    record = {"id": "K1", "question": question, "facts": [unrelated, relevant]}
    full, _ = lr._kiq_digest_block(record, 10_000, "English")
    cap = len(full) + 60 - len(unrelated["text"]) - 3
    fair, lost = lr._kiq_digest_block(record, cap, "English", relevance_drop=True)
    findings = fair.split("Findings:", 1)[1]
    assert lost == 1 and "grid connection queues" in findings and "logo" not in findings
    plain, lost = lr._kiq_digest_block(record, cap, "English")
    findings = plain.split("Findings:", 1)[1]
    assert lost == 1 and "logo" in findings and "grid connection queues" not in findings  # today: the later one goes


# =============================================================== scout fairness

def _result(sid, body):
    return f"[S{sid}] Title {sid} — site{sid}.org\n{body}"


def _scout_engine(results, *, fairness):
    engine = lr._Engine.__new__(lr._Engine)
    engine.tools = types.SimpleNamespace(search=lambda query, agent_id: results[query])
    engine.gateway = types.SimpleNamespace(fan_out=lambda jobs, warm_first, workers: [job() for job in jobs])
    engine.preset = types.SimpleNamespace(workers=2)
    engine.truncation_fairness = fairness
    return engine


def test_fair_scout_keeps_every_query_and_cuts_only_between_results():
    queries = [f"query {i}" for i in range(6)]
    bodies = {1: "a" * 5000, 2: "short second result", 3: "short third result"}
    results = {q: "\n".join(_result(10 * i + k, body) for k, body in bodies.items())
               for i, q in enumerate(queries)}
    digest = _scout_engine(results, fairness=True)._scout(queries)
    assert len(digest) <= lr.SCOUT_DIGEST_CHARS
    for query in queries:
        assert f"Query: {query}" in digest
    kept = re.findall(r"^\[S(\d+)\] [^\n]*\n([^\n]*)", digest, re.M)
    assert all(body == bodies[int(sid) % 10] for sid, body in kept)    # never a partial result
    # the oversized first result is left out whole; the shorter ones after it stay
    assert sorted(int(sid) for sid, _ in kept) == sorted(10 * i + k for i in range(6) for k in (2, 3))
    assert digest.count("(1 results omitted for length)") == 6
    head_cut = _scout_engine(results, fairness=False)._scout(queries)
    assert "Query: query 5" not in head_cut                 # today the last queries vanish


def test_fair_scout_off_is_todays_head_cut_and_within_cap_is_unchanged():
    queries = [f"q{i}" for i in range(4)]
    results = {q: _result(i + 1, ("line of text\n" * 200)) for i, q in enumerate(queries)}
    parts = [f"Query: {q}\n{results[q]}" for q in queries]
    expected = "\n\n".join(parts)[:lr.SCOUT_DIGEST_CHARS].rsplit("\n", 1)[0]
    assert _scout_engine(results, fairness=False)._scout(queries) == expected
    small = {q: _result(i + 1, "tiny") for i, q in enumerate(queries)}
    assert (_scout_engine(small, fairness=True)._scout(queries)
            == _scout_engine(small, fairness=False)._scout(queries))
    shares = lr.fair_scout_digest(["Query: a\n" + "x" * 50, "Query: b\n" + _result(1, "y" * 9000)], 6000)
    assert shares.startswith("Query: a\n" + "x" * 50) and "(1 results omitted for length)" in shares


# =============================================================== end to end

def _run(tmp_path, bridge, monkeypatch, name, *, headers=False, fairness=False, fetch=None, gap_rounds=None):
    _set_knobs(monkeypatch, headers=headers, fairness=fairness)
    if gap_rounds is not None:
        monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", str(gap_rounds))
    rc, meta, plog, model, out = v3.run_engine(tmp_path / name, bridge, v3.World(), fetch=fetch)
    assert rc == 0, meta.get("error")
    return meta, model, out


def _task(model, role):
    return [call["messages"][-1][1] for call in v3.calls_of(model, role)]


def test_flags_off_by_default_leave_digest_prompts_and_meta_untouched(tmp_path, bridge, monkeypatch):
    for name in KNOBS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", "1")
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, v3.World())
    assert rc == 0, meta.get("error")
    digest = (out / "v3" / "digest.md").read_text(encoding="utf-8")
    assert "Evidence (engine count)" not in digest and lr.EVIDENCE_HEADER_LEGEND not in digest
    assert all(block.splitlines()[1] == "Findings:" for block in digest.split("\n### ")[1:])
    gap = _task(model, "GAP REVIEW TASK")
    assert gap and not any("sufficiency=" in t for t in gap)
    assert not any(lr._SECTION_THIN_EVIDENCE_RULE in t for t in _task(model, "SECTION WRITING TASK"))
    assert "evidence" not in meta["kiqs"] and "sufficiency" not in meta["kiqs"]
    assert "insufficient evidence" not in json.dumps(meta)


def test_headers_on_feed_digest_coverage_section_rule_and_meta(tmp_path, bridge, monkeypatch):
    meta, model, out = _run(tmp_path, bridge, monkeypatch, "on", headers=True, gap_rounds=1)
    digest = (out / "v3" / "digest.md").read_text(encoding="utf-8")
    assert lr.EVIDENCE_HEADER_LEGEND in digest
    blocks = digest.split("\n### ")[1:]
    assert blocks and all(HEADER_RE.match(block.splitlines()[1]) for block in blocks)
    gap = _task(model, "GAP REVIEW TASK")
    assert gap and all(re.search(r"fetched=\d+ domains=\d+ sufficiency=(?:insufficient|thin|adequate)", t)
                       for t in gap)
    sections = _task(model, "SECTION WRITING TASK")
    assert sections and all(lr._SECTION_THIN_EVIDENCE_RULE in t for t in sections)
    evidence = meta["kiqs"]["evidence"]
    researched = sorted(path.stem for path in (out / "v3" / "kiq").glob("*.json"))
    assert sorted(evidence) == researched
    assert sum(meta["kiqs"]["sufficiency"].values()) == len(researched)
    assert set(meta["kiqs"]["sufficiency"]) == set(lr.SUFFICIENCY_LABELS)


def test_insufficient_majority_raises_a_degradation_event(tmp_path, bridge, monkeypatch):
    def no_fetch(url):
        raise OSError("fetch blocked in this test")

    meta, _, _ = _run(tmp_path, bridge, monkeypatch, "on", headers=True, fetch=no_fetch)
    profiles = meta["kiqs"]["evidence"]
    assert profiles and all(p["sufficiency"] == "insufficient" for p in profiles.values())
    assert re.search(r"\d+ of \d+ researched KIQs have insufficient evidence", json.dumps(meta))
    off_meta, _, _ = _run(tmp_path, bridge, monkeypatch, "off", fetch=no_fetch)
    assert "insufficient evidence" not in json.dumps(off_meta)


# =============================================================== knobs and wiring

def test_knobs_documented_forwarded_and_drift_clean(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import check_env_drift as drift

    defaults = drift.config_defaults()
    assert all(defaults[name] == "false" for name in KNOBS)
    assert set(KNOBS) <= drift.documented_env_vars()
    strict = subprocess.run([sys.executable, drift.__file__, "--strict"], capture_output=True, text=True,
                            timeout=60)
    assert strict.returncode == 0, strict.stdout
    assert set(KNOBS) <= set(v3._ENV_EXACT)
    for name in KNOBS:
        assert (name, "bool") in po.RESEARCH_CHILD_V3_KNOBS
    for name, value, expected in (("on", True, "true"), ("off", False, "false")):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", "v3", raising=False)
        for knob in KNOBS:
            monkeypatch.setattr(po.Config, knob, value, raising=False)
            monkeypatch.setenv(knob, "false" if value else "true")    # ambient never decides
        child = _launch_capturing_child(monkeypatch, tmp_path / name, timeout=900)
        assert all(child["env"][knob] == expected for knob in KNOBS)
