"""Review round 3 regressions of the deep-research engine v3: the KIQ agent loop
and the research-notes parser (cluster "engine loop").

C6 heading/bullet/notes patterns run in linear time on long whitespace runs;
C12/C29 a reading plan written as cited bullets before any research is nudged,
never accepted as findings; C30 once the nudge is spent a reply with neither
tool calls nor notes gets the STOP turn; C31 findings written as plain lines,
tables or other list markers under a heading are kept; C32/C24 numbered or
id-suffixed headings are recognised, so conflicts, open questions and leads
never become facts; C33 notes cut by the output cap are asked for once more
with a wider cap, then trimmed and flagged, and a reply left empty at the cap
ends retryable; C36/C20 deterministic notes pick KIQ-relevant numeric
sentences and skip page chrome; C38 same-step duplicate tool calls run once;
C39 a re-read naming another entity, year or figure is not refused.

Offline and deterministic: the fakes and ``run_engine`` harness of
``test_research_engine_v3`` (scripted model, injected search/fetch, the real
bridge module with prediction markets and charts stubbed), injected clocks,
no sleeps.  The one wall-clock guard (C6) uses a bound far above the linear
cost and far below the old polynomial one.
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
import time
import types

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg

_KIQ = lr.Kiq(id="K1", question="What is installed data-centre capacity?", queries=[], kind="data")
NOTES = ("## Findings\n- Installed capacity reached 176 GW in 2023 [S1] (VERIFIED)\n"
         "- The agency projects demand growth of 12% per year through 2027 [S1] (REPORTED)\n"
         "## Conflicts\n- none\n## Open questions\n- 2025 capacity\n## Discovered\n- grid queues")


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _agent_engine(tmp_path, model, *, fetch=None, logs=None, steps: int = 7):
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", search_fn=v3.fake_search,
                             fetch_fn=fetch or v3.page_text)
    gateway = rg.ModelGateway(model, None, sleep=lambda s: None)
    sink = logs if logs is not None else []
    return types.SimpleNamespace(
        gateway=gateway, tools=tools, ledger=ledger, brief="RUN BRIEF\nquestion", language="English",
        preset=types.SimpleNamespace(agent_max_steps=steps, workers=4),
        log=lambda kind, msg: sink.append((kind, msg)), units=lambda tokens: float(tokens))


def _scripted(*replies):
    """A model answering its i-th call with ``replies[i]`` (the last one
    repeats); a callable reply is called with the recorded call."""
    state = {"n": 0}

    def responder(call):
        reply = replies[min(state["n"], len(replies) - 1)]
        state["n"] += 1
        return reply(call) if callable(reply) else reply

    return v3.ScriptedModel(responder)


def _call(name: str, args: dict, cid: str) -> dict:
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


FETCH = v3.ai(tool_calls=[_call("web_fetch", {"url": "https://agency0.org/r", "focus": "installed capacity"},
                                "c1")])


def _parts(engine, notes: str) -> dict:
    _, parts = lr.postprocess_notes("K1", notes, engine.ledger.get,
                                    lambda sid: lr.page_number_set(engine.tools.page_text(sid) or ""))
    return parts


def _record(out, kid: str) -> dict:
    return json.loads((out / "v3" / "kiq" / f"{kid}.json").read_text(encoding="utf-8"))


def _kid(call: dict) -> str:
    return re.search(r"Investigate (\S+):", call["messages"][2][1]).group(1)


# =============================================================== C6 linear-time patterns

_OLD_WRITER_HEADING_RE = re.compile(r"^\s{0,3}(#{1,2})\s+(.+?)\s*#*\s*$")


def _quick(action):
    """Run ``action``; each case below took 2.5-5.5 s with the old patterns
    (polynomial in the run length) and takes milliseconds in linear time."""
    started = time.perf_counter()
    result = action()
    assert time.perf_counter() - started < 1.0
    return result


def test_r3_notes_patterns_stay_linear_on_long_whitespace_runs():
    """A notes line with a long interior space/tab run took O(k^3) in the
    heading pattern (2,000 spaces: 5.5 s; 4,000: 44 s); cited bullets, the
    space tidier, the citation normaliser and writer headings were polynomial
    on such runs too."""
    assert _quick(lambda: lr.has_notes_structure("Summary" + "\t" * 1800 + "x")) is False
    assert _quick(lambda: lr._note_heading("Findings" + "　" * 20_000 + "z")) is None
    assert _quick(lambda: lr.has_notes_structure("- " + " " * 30_000)) is False
    rows = {1: {"sid": 1}}.get
    _, parts = _quick(lambda: lr.postprocess_notes("K1", "## Findings\n- a fact [S1]" + " " * 50_000, rows,
                                                   lambda sid: None))
    assert [f["text"] for f in parts["facts"]] == ["a fact [S1]"]
    _, parts = _quick(lambda: lr.postprocess_notes("K1", "## Findings\n- a fact [S1" + " " * 1200 + "x", rows,
                                                   lambda sid: None))
    assert parts["facts"] == [] and parts["unsourced"] == ["a fact [S1 x"]
    assert _quick(lambda: lr._tidy_spaces("a" + " " * 50_000)) == "a" + " " * 50_000
    sections = _quick(lambda: lr.split_writer_output("## a" + " " * 1800 + "b\nbody", ["a"]))
    assert sections == {"a": "### a" + " " * 1800 + "b\n\nbody"}


def test_r3_writer_heading_matches_the_old_pattern_exactly():
    """The linear _writer_heading replaces a backtracking pattern used by
    synthesis: same matching lines, same heading text."""
    fixed = ["## Title", "# T ##", "## C#", "##   ", "## ", "### T", "    ## T", "   ## T  ##  ",
             "##\tA  #  #", "#x", "## #", "## # #", "　## T", "## 5G outlook ###"]
    rng = random.Random(3)
    alphabet = [" ", "\t", "#", "a", "B", ".", ":", "　", "\xa0", "*"]
    lines = fixed + ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 9))) for _ in range(20_000)]
    for line in lines:
        match = _OLD_WRITER_HEADING_RE.match(line)
        assert lr._writer_heading(line) == (match.group(2) if match else None), repr(line)


# =============================================================== C12 / C29 cited plans

PLAN = ("I will verify the capacity figure before writing notes:\n"
        "1. Fetch [S1] for the official capacity series\n"
        "2. Cross-check against [S2] and the grid-queue data in [S3]")


def _seeded_engine(tmp_path, model, **kwargs):
    engine = _agent_engine(tmp_path, model, **kwargs)
    for n in range(3):
        engine.ledger.register(f"https://agency{n}.org/r", f"Capacity report {n}", "176 GW in 2023",
                               "search", "seeder")
    return engine


def test_r3_a_cited_plan_on_the_first_step_is_nudged_and_the_agent_researches(tmp_path):
    fetch_seed = v3.ai(tool_calls=[_call("web_fetch", {"url": "S1", "focus": "installed capacity"}, "c1")])
    model = _scripted(v3.ai(PLAN), fetch_seed, v3.ai(NOTES))
    engine = _seeded_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [1, 2, 3], rg.Deadline(600)).run()
    assert model.calls[1]["messages"][-2:] == [("ai", PLAN), ("human", lr.NOTES_NUDGE_TEXT)]
    assert outcome.fallback is None and outcome.fetched == [1] and len(model.calls) == 3
    texts = [f["text"] for f in _parts(engine, outcome.notes)["facts"]]
    assert any("176 GW" in text for text in texts)
    assert not any("Fetch" in text or "Cross-check" in text for text in texts)


def test_r3_a_persistent_cited_plan_never_becomes_findings(tmp_path):
    model = _scripted(v3.ai(PLAN))
    engine = _seeded_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [1, 2, 3], rg.Deadline(600)).run()
    # The reply, one nudge, then the STOP turn: a plan is still no notes.
    assert len(model.calls) == 3 and model.calls[2]["messages"][-1] == ("human", lr.STOP_TEXT)
    assert outcome.fallback == "unstructured_notes" and outcome.forced == "no_notes"
    assert outcome.fallback in lr._RETRYABLE_FALLBACKS
    texts = [f["text"] for f in _parts(engine, outcome.notes)["facts"]]
    assert texts and not any("Fetch" in text or "Cross-check" in text for text in texts)


def test_r3_cited_bullets_without_a_heading_are_notes_once_the_agent_has_researched(tmp_path):
    bullets = ("- Installed capacity reached 176 GW in 2023 [S1] (VERIFIED)\n"
               "- The agency projects demand growth of 12% per year through 2027 [S1]")
    model = _scripted(FETCH, v3.ai(bullets))
    engine = _agent_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600)).run()
    assert len(model.calls) == 2 and outcome.fallback is None and outcome.notes == bullets
    assert [f["tag"] for f in _parts(engine, outcome.notes)["facts"]] == ["VERIFIED", "REPORTED"]


class PlanWorld(v3.World):
    """K2 answers its first step with a plan citing its seed rows."""

    def agent(self, call):
        if _kid(call) == "K2" and len(call["messages"]) == 3:
            sids = re.findall(r"^\[S(\d+)\]", call["messages"][2][1], re.M)[:2]
            return v3.ai(f"Plan before reading:\n1. Fetch [S{sids[0]}] for the official demand series\n"
                         f"2. Cross-check the growth drivers against [S{sids[1]}]")
        return super().agent(call)


def test_r3_a_cited_plan_never_reaches_the_digest(tmp_path, bridge):
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, PlanWorld())
    assert rc == 0, meta.get("error")
    record = _record(out, "K2")
    assert record["stats"]["fallback"] is None and record["stats"]["fetched"]
    assert not any("Fetch" in f["text"] or "Cross-check" in f["text"] for f in record["facts"])
    digest = (out / "v3" / "digest.md").read_text(encoding="utf-8")
    assert "official demand series" not in digest and "Cross-check" not in digest


# =============================================================== C30 nudge spent

def test_r3_a_second_narration_gets_the_stop_turn_and_keeps_the_research(tmp_path):
    def announce_or_notes(call):
        if call["messages"][-1] == ("human", lr.STOP_TEXT):
            return v3.ai(NOTES)
        return v3.ai("I now have enough evidence from the agency report; I will write my final notes next.")

    model = _scripted(v3.ai("I'll begin by looking for the official statistics release."),
                      v3.ai(tool_calls=[_call("web_search", {"query": "installed capacity 2023"}, "c1")]),
                      v3.ai(tool_calls=[_call("web_fetch", {"url": "S1", "focus": "installed capacity"}, "c2")]),
                      announce_or_notes)
    engine = _agent_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600)).run()
    assert model.calls[-1]["messages"][-1] == ("human", lr.STOP_TEXT)
    assert outcome.fallback is None and outcome.forced == "no_notes" and outcome.fetched == [1]
    facts = _parts(engine, outcome.notes)["facts"]
    assert [(f["tag"], f["text"]) for f in facts][0] == ("VERIFIED", "Installed capacity reached 176 GW in 2023 [S1]")


# =============================================================== C31 findings without list markers

_TAIL = "\n## Conflicts\n- none\n## Open questions\n- 2025 capacity\n## Discovered\n- grid queues"
_FACT_A = "Installed capacity reached 176 GW in 2023"
_FACT_B = "Demand grows 12% per year through 2027"


@pytest.mark.parametrize("findings", [
    f"{_FACT_A} [S1] (VERIFIED)\n{_FACT_B} [S1] (REPORTED)",
    f"{_FACT_A} [S1] (VERIFIED)\n\n{_FACT_B} [S1] (REPORTED)",
    f"{_FACT_A} [S1] (VERIFIED). {_FACT_B} [S1] (REPORTED).",
    f"| Fact | Source | Tag |\n|---|---|---|\n| {_FACT_A} | [S1] | VERIFIED |\n| {_FACT_B} | [S1] | REPORTED |",
    f"– {_FACT_A} [S1] (VERIFIED)\n– {_FACT_B} [S1] (REPORTED)",
    f"+ {_FACT_A} [S1] (VERIFIED)\n+ {_FACT_B} [S1] (REPORTED)",
    f"1、{_FACT_A} [S1] (VERIFIED)\n2、{_FACT_B} [S1] (REPORTED)",
    f"（1）{_FACT_A} [S1] (VERIFIED)\n（2）{_FACT_B} [S1] (REPORTED)",
    f"① {_FACT_A} [S1] (VERIFIED)\n② {_FACT_B} [S1] (REPORTED)",
    f"**1.** {_FACT_A} [S1] (VERIFIED)\n**2.** {_FACT_B} [S1] (REPORTED)",
])
def test_r3_findings_without_dash_bullets_are_facts(findings):
    rows = {1: {"sid": 1, "fetched": True}}
    _, parts = lr.postprocess_notes("K1", "## Findings\n" + findings + _TAIL, rows.get,
                                    lambda sid: frozenset({"176", "2023"}))
    assert [(f["tag"], f["text"].rstrip(".")) for f in parts["facts"]] == [
        ("VERIFIED", f"{_FACT_A} [S1]"), ("REPORTED", f"{_FACT_B} [S1]")]
    assert parts["unsourced"] == [] and parts["open_questions"] == ["2025 capacity"]


def test_r3_plain_note_lines_keep_their_sections_and_wrapped_bullets():
    rows = {n: {"sid": n, "fetched": True} for n in (1, 2)}
    notes = ("Here are my notes.\n## Findings\n- Capacity reached 176 GW in 2023 [S1]\n  as the agency's survey shows\n"
             "| Region | Capacity | Source |\n|---|---|---|\n| Europe | 40 GW | [S2] |\n\nSources: [S1], [S2]\n"
             "## Open questions\nWhether the 6.5 GW under construction is energised by 2025\n"
             "**Conflicts:** [S1] says 176 GW while [S2] says 181 GW\nDiscovered: on-site generation")
    _, parts = lr.postprocess_notes("K1", notes, rows.get, lambda sid: frozenset({"176", "2023"}))
    assert [f["text"] for f in parts["facts"]] == [
        "Capacity reached 176 GW in 2023 [S1] as the agency's survey shows", "Europe 40 GW [S2]"]
    assert parts["open_questions"] == ["Whether the 6.5 GW under construction is energised by 2025"]
    assert parts["conflicts"] == ["[S1] says 176 GW while [S2] says 181 GW"]
    assert parts["discovered"] == ["on-site generation"] and parts["unsourced"] == []


def test_r3_an_agent_writing_plain_finding_lines_keeps_its_notes(tmp_path):
    plain = ("## Findings\nInstalled capacity reached 176 GW in 2023 [S1] (VERIFIED)\n"
             "Demand grows 12% per year through 2027 [S1] (REPORTED)" + _TAIL)
    model = _scripted(FETCH, v3.ai(plain))
    engine = _agent_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600)).run()
    assert outcome.fallback is None and outcome.notes == plain
    assert [f["tag"] for f in _parts(engine, outcome.notes)["facts"]] == ["VERIFIED", "REPORTED"]


# =============================================================== C32 / C24 heading variants

@pytest.mark.parametrize("headings", [
    ("## 1. Findings", "## 2. Conflicts", "## 3. Open questions", "## 4. Discovered"),
    ("1. Findings", "2. Conflicts", "3. Open questions", "4. Discovered"),
    ("1) Findings", "2) Conflicts", "3) Open questions", "4) Discovered"),
    ("**1. Findings**", "**2. Conflicts:**", "**3. Open questions:**", "**4. Discovered**"),
    ("1. **Findings:**", "2. **Conflicts:**", "3. **Open questions:**", "4. **Discovered:**"),
    ("## Findings (K1)", "## Conflicts (K1)", "## Open questions (K1)", "## Discovered (K1)"),
    ("### 关键发现（K3）", "### 冲突（K3）", "### 未决问题（K3）", "### 新线索（K3）"),
    ("## 一、关键发现", "## 二、冲突", "## 三、未决问题", "## 四、新线索"),
    ("## Findings for K1", "## Conflicts — K1", "## K1 Open questions", "## Discovered: K1"),
])
def test_r3_numbered_or_id_headings_keep_every_section(headings):
    rows = {n: {"sid": n, "fetched": True} for n in range(1, 9)}
    notes = (f"{headings[0]}\n- Installed capacity reached 176 GW in 2023 [S4] (VERIFIED)\n"
             f"{headings[1]}\n- [S4] says 176 GW while [S5] says 181 GW for 2023; definitions differ\n"
             f"{headings[2]}\n- Whether the 6.5 GW under construction in [S5] is energised by 2025\n"
             f"{headings[3]}\n- Grid-queue reform mentioned in [S6] could change connection times")
    assert lr.has_notes_heading(notes)
    _, parts = lr.postprocess_notes("K1", notes, rows.get, lambda sid: frozenset({"176", "2023"}))
    assert [f["text"] for f in parts["facts"]] == ["Installed capacity reached 176 GW in 2023 [S4]"]
    assert (len(parts["conflicts"]), len(parts["open_questions"]), len(parts["discovered"])) == (1, 1, 1)
    assert parts["unsourced"] == []


# =============================================================== C33 cut agent notes

CUT = ("## Findings\n- Installed capacity reached 176 GW in 2023 [S1] (VERIFIED)\n"
       "- The agency projects demand growth of 12% per year through 2027 [S1] (REPORTED)\n"
       "- Grid connection queues exceed 40 mon")


def _caps(model) -> list[int]:
    return [call["kwargs"].get("max_tokens") for call in model.calls]


def test_r3_cut_notes_get_one_wider_try_then_keep_their_complete_lines(tmp_path):
    logs: list = []
    model = _scripted(FETCH, v3.ai(CUT, finish="length"))
    engine = _agent_engine(tmp_path, model, logs=logs)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600)).run()
    assert _caps(model) == [6000, 6000, lr.AGENT_RETRY_MAX_TOKENS]
    assert outcome.fallback is None and outcome.truncated is True
    assert "40 mon" not in outcome.notes
    parts = _parts(engine, outcome.notes)
    assert [f["tag"] for f in parts["facts"]] == ["VERIFIED", "REPORTED"] and parts["unsourced"] == []
    assert any(kind == "warn" and "cut at their output cap" in msg for kind, msg in logs)


def test_r3_a_wider_notes_call_that_fits_keeps_the_whole_notes(tmp_path):
    model = _scripted(FETCH, v3.ai(CUT, finish="length"), v3.ai(NOTES))
    engine = _agent_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600)).run()
    assert outcome.notes == NOTES and outcome.truncated is False and outcome.fallback is None


def test_r3_no_wider_try_when_the_deadline_cannot_cover_it(tmp_path):
    clock = _Clock()
    model = _scripted(FETCH, v3.ai(CUT, finish="length"))
    engine = _agent_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(lr.TRUNCATION_RETRY_MIN_SECONDS - 1, clock)).run()
    assert _caps(model) == [6000, 6000] and outcome.truncated is True and outcome.fallback is None


def test_r3_reasoning_that_uses_the_whole_cap_ends_retryable_not_empty(tmp_path):
    """The gateway retries a reply its cap cut before any text once with a
    wider cap and then raises EmptyResponse(truncated=True); the agent does
    not widen again and ends retryable, keeping its reading."""
    model = _scripted(FETCH, v3.ai("", finish="length"))
    engine = _agent_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600)).run()
    assert sum(cap > 6000 for cap in _caps(model)) == 1  # one wider try in all
    assert outcome.fallback == "notes_truncated" and outcome.fallback in lr._RETRYABLE_FALLBACKS
    assert outcome.fetched == [1] and _parts(engine, outcome.notes)["facts"]  # its reading is kept


def test_r3_an_empty_reply_that_stopped_normally_is_still_empty(tmp_path):
    model = _scripted(FETCH, v3.ai("", finish="stop"))
    engine = _agent_engine(tmp_path, model)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600)).run()
    assert outcome.fallback == "empty" and _caps(model) == [6000, 6000, 6000]


class _ReasoningOnlyFirstNotes:
    """A gateway that serves the first tool-less agent reply as an empty
    result cut by its output cap."""

    def __init__(self, gateway) -> None:
        self._gateway = gateway
        self.served = False

    def __getattr__(self, name):
        return getattr(self._gateway, name)

    def invoke(self, messages, **kwargs):
        result = self._gateway.invoke(messages, **kwargs)
        if not self.served and not result.tool_calls:
            self.served = True
            return dataclasses.replace(result, text="", finish_reason="length", truncated=True)
        return result


def test_r3_an_empty_cut_result_is_asked_for_once_more_with_a_wider_cap(tmp_path):
    model = _scripted(FETCH, v3.ai(NOTES))
    engine = _agent_engine(tmp_path, model)
    engine.gateway = _ReasoningOnlyFirstNotes(engine.gateway)
    outcome = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600)).run()
    assert _caps(model) == [6000, 6000, lr.AGENT_RETRY_MAX_TOKENS]
    assert outcome.fallback is None and outcome.notes == NOTES


class CutNotesWorld(v3.World):
    """K1's notes always stop at the output cap in the middle of a finding."""

    def agent(self, call):
        reply = super().agent(call)
        if _kid(call) == "K1" and not reply.tool_calls:
            return v3.ai(reply.content + "\n- A dangling finding cut at 17", finish="length")
        return reply


def test_r3_cut_notes_are_flagged_on_the_kiq_record(tmp_path, bridge):
    rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, CutNotesWorld())
    assert rc == 0, meta.get("error")
    record = _record(out, "K1")
    assert record["stats"]["truncated"] is True and record["stats"]["fallback"] is None
    assert record["facts"] and not any("dangling" in f["text"] for f in record["facts"])
    assert _record(out, "K2")["stats"]["truncated"] is False
    assert any(c["kwargs"]["max_tokens"] == lr.AGENT_RETRY_MAX_TOKENS
               for c in v3.calls_of(model, "agent") if _kid(c) == "K1")
    assert "K1 notes were cut at their output cap" in plog.text()


# =============================================================== C36 / C20 deterministic notes

NEWS_PAGE = (
    "# Grid operator sees record data-centre demand\n\n"
    "By Jane Doe, Energy Correspondent. Published 12 March 2024, updated 14 March 2024 at 10:32 GMT.\n\n"
    "We use 3 types of cookies to improve your experience on our website; see our privacy policy for details.\n"
    "Home | Markets | Energy | Tech\n"
    "By Staff Reporter | September 15, 2026 | 4 min read | 23 comments\n\n"
    "[Skip to main content](https://news.example.com/2024/03/12/grid#main)\n\n"
    "Shares of the operator rose 3.1% on Tuesday after the company reported a record number of connection requests.\n\n"
    "According to the operator's annual report, installed data-centre capacity in the state reached 4.2 GW "
    "at the end of 2023, up from 2.9 GW a year earlier.\n\n"
    "© 2024 News Corp. All rights reserved.")


def test_r3_numeric_sentences_skip_page_chrome_and_prefer_the_kiq():
    chrome = ("Published", "cookies", "Home |", "Staff Reporter", "Skip to", "©")
    unranked = lr.numeric_sentences(NEWS_PAGE, 5)
    assert unranked and not any(word in sentence for sentence in unranked for word in chrome)
    ranked = lr.numeric_sentences(NEWS_PAGE, 2, terms=rg.query_terms(_KIQ.question))
    assert ranked == ["According to the operator's annual report, installed data-centre capacity in the state "
                      "reached 4.2 GW at the end of 2023, up from 2.9 GW a year earlier."]
    # No sentence matches the terms: the page's first numeric sentences.
    assert lr.numeric_sentences(NEWS_PAGE, 1, terms=["zeppelin"]) == unranked[:1]


def test_r3_numeric_sentences_never_glue_a_header_line_onto_a_sentence():
    page = ("Data centre outlook\n-------------------\n\nMarket update\n"
            "Electricity demand from data centres grew 12% in 2025, the agency said, after rising 18% in 2024.\n"
            "This long wrapped line of the same paragraph keeps going without any end punctuation and\n"
            "ends on the next line with 40 months of queue.")
    assert lr.numeric_sentences(page, 3) == [
        "Electricity demand from data centres grew 12% in 2025, the agency said, after rising 18% in 2024.",
        "This long wrapped line of the same paragraph keeps going without any end punctuation and ends on the "
        "next line with 40 months of queue."]


def test_r3_fallback_notes_keep_the_figure_the_kiq_asks_for(tmp_path):
    engine = _agent_engine(tmp_path, _scripted(v3.ai("unused")), fetch=lambda url: NEWS_PAGE)
    agent = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600))
    agent._execute([_call("web_fetch", {"url": "https://news.example.com/grid", "focus": "capacity"}, "c1")])
    notes = agent.fallback_notes("deadline")
    facts = [f["text"] for f in _parts(engine, notes)["facts"]]
    assert len(facts) == 1 and "4.2 GW" in facts[0]
    assert not any(word in facts[0] for word in ("Published", "cookies", "Shares", "Staff Reporter"))


# =============================================================== C38 same-step duplicates

def _counting_fetch(calls: list):
    def fetch(url):
        calls.append(url)
        return v3.page_text(url)
    return fetch


def test_r3_same_step_twins_of_a_page_not_yet_stored_run_once(tmp_path):
    fetched: list = []
    engine = _agent_engine(tmp_path, _scripted(v3.ai("unused")), fetch=_counting_fetch(fetched))
    agent = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600))
    messages, novel = agent._execute([
        _call("web_fetch", {"url": "https://agency.org/report", "focus": "installed capacity"}, "a"),
        _call("web_fetch", {"url": "http://www.agency.org/report/", "focus": "capacity installed"}, "b"),
        _call("web_search", {"query": "installed capacity 2023"}, "c"),
    ])
    assert novel and len(fetched) == 1
    assert lr.tool_output_sids("web_fetch", messages[0].content)[0] == agent.fetched[0]
    assert messages[1].content == lr.DUPLICATE_CALL_TEXT
    assert [m.tool_call_id for m in messages] == ["a", "b", "c"]
    assert lr.tool_output_sids("web_search", messages[2].content)[1]  # the search ran


def test_r3_same_step_marker_twin_and_repeated_search_run_once(tmp_path):
    fetched: list = []
    engine = _agent_engine(tmp_path, _scripted(v3.ai("unused")), fetch=_counting_fetch(fetched))
    row = engine.ledger.register("https://agency.org/report", "Agency report", "", "search", "seeder")
    agent = lr.KiqAgent(engine, _KIQ, "task", [row["sid"]], rg.Deadline(600))
    messages, _ = agent._execute([
        _call("web_fetch", {"url": f"S{row['sid']}", "focus": "installed capacity 2023"}, "a"),
        _call("web_fetch", {"url": "https://agency.org/report", "focus": "installed capacity"}, "b"),
        _call("web_search", {"query": "grid  queue"}, "c"),
    ])
    assert len(fetched) == 1 and messages[1].content == lr.DUPLICATE_CALL_TEXT
    messages, _ = agent._execute([_call("web_search", {"query": "Grid queue"}, "d"),
                                  _call("web_search", {"query": "grid queue "}, "e")])
    assert messages[1].content == lr.DUPLICATE_CALL_TEXT and messages[0].content != lr.DUPLICATE_CALL_TEXT


def test_r3_same_step_reads_of_a_page_with_different_focuses_both_run(tmp_path):
    engine = _agent_engine(tmp_path, _scripted(v3.ai("unused")))
    agent = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600))
    messages, _ = agent._execute([
        _call("web_fetch", {"url": "https://agency.org/report", "focus": "installed capacity"}, "a"),
        _call("web_fetch", {"url": "https://agency.org/report", "focus": "capital expenditure"}, "b"),
    ])
    assert all(m.content.startswith("[S1]") for m in messages)


# =============================================================== C39 ALREADY_READ

_COUNTRIES = ["China", "Japan", "Germany", "Brazil", "Mexico", "Canada", "Korea", "France", "Spain", "Italy",
              "Chile", "Peru", "Egypt", "Kenya", "Norway", "Sweden", "Poland", "Turkey", "Vietnam", "India"]
STATS_PAGE = "# Global capacity statistics 2023\n\n" + "\n\n".join(
    f"{country} installed capacity reached {10 + i}.{i} GW in 2023 according to the national statistics "
    f"office, with further additions planned by regional utilities and private developers over the coming years."
    for i, country in enumerate(_COUNTRIES))


def test_r3_a_re_read_for_another_entity_or_year_is_served(tmp_path):
    engine = _agent_engine(tmp_path, _scripted(v3.ai("unused")), fetch=lambda url: STATS_PAGE)
    agent = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600))

    def read(focus: str) -> str:
        messages, _ = agent._execute([_call("web_fetch", {"url": "https://stats.example.org/capacity",
                                                          "focus": focus}, "c")])
        return messages[0].content

    first = read("China installed capacity 2023")
    assert "China installed" in first and "India installed" not in first
    assert "India installed" in read("India installed capacity 2023")        # entity swap (3/5)
    assert not read("India installed capacity 2022").startswith("ALREADY_READ")  # year swap
    assert read("installed capacity India").startswith("ALREADY_READ")       # nothing new asked
    assert read("China capacity installed 2023").startswith("ALREADY_READ")  # same terms reordered


def test_r3_near_same_generic_focuses_follow_the_restructured_threshold(tmp_path):
    engine = _agent_engine(tmp_path, _scripted(v3.ai("unused")))
    row = engine.ledger.register("https://agency.gov/r", "Agency", "", "search", "K1")
    engine.ledger.mark_fetched(row["sid"], content_sha256="0" * 64, chars=400, page_path="pages/x.txt")
    agent = lr.KiqAgent(engine, _KIQ, "task", [], rg.Deadline(600))

    def read(focus: str) -> str | None:
        call = {"name": "web_fetch", "args": {"url": "https://agency.gov/r", "focus": focus}, "id": "c"}
        return agent._screen_read(call, agent._focus_terms(call))

    assert read("installed capacity growth outlook") is None
    assert read("installed capacity growth forecast") is None                 # one-term swap of four (3/5)
    assert read("installed capacity growth forecast rates") is not None       # adds one term to four (4/5)
    assert lr.specific_terms("India installed capacity 2023") == frozenset({"india", "2023"})
