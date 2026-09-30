"""RESEARCH-3: absence-of-evidence discipline for the v3 research engine.

RESEARCH_ABSENCE_DISCIPLINE (default false):

* an empty web search answers ``MSG_NO_RESULTS_COVERAGE`` (NO_RESULTS plus
  "an empty search is not evidence that something did not happen"), as
  cacheable as NO_RESULTS;
* the KIQ task and the section rules each gain one absence line through the
  shared ``_kiq_task_addenda`` / ``_section_rule_addenda`` hooks (volatile
  last-message text: ENGINE_CORE and the brief never change);
* findings that state an absence are counted, observe only: KIQ records get
  ``absence_cues`` and meta ``absence_findings``; no tag changes.

Off, the tool text and every prompt are byte-identical.  Also here: REPORT-4's
``absence.market_status`` maps the bridge's explicit partial_transport_failure
label to unavailable, and the knob's Config default and child forwarding.
Offline: the scripted model, injected search/fetch and real bridge of
``test_research_engine_v3``.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import types
from collections import Counter
from pathlib import Path

import pytest

import test_research_engine_v3 as v3
from app.utils import absence
from test_research_engine_v3_evidence import KIQ_TASK_SHA256

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg
po = v3.po

COVERAGE_SENTENCE = (" Results are relevance-ranked and undated: an empty search is not evidence that "
                     "something did not happen.")
KIQ_RULE = ("Absence: an empty or failed search is not evidence that something did not happen. Write that "
            "something did not happen or was not reported only when a source you read says so, and cite it; "
            "otherwise record it under Open questions.")
SECTION_RULE = ("- Never state that something did not happen, was not reported or does not exist unless a cited "
                "source says so; otherwise say the sources reviewed do not establish it.")
# section_task of _section_engine() for _SECTIONS before this package (no note / a
# rewrite note and current body): off must render these bytes.
SECTION_TASK_SHA256 = "4f55557a677d1f822dc0c7b4097ad876c9123af694b3e091408058a9f969b826"
SECTION_REWRITE_TASK_SHA256 = "bf12d68c6c3b1c8955ea5891191bf624b4ba4cad27867103b3781e632487f616"
_SECTIONS = [lr.OutlineSection(index=1, title="Market Baseline", kiq_ids=["K1", "K2"], focus="base year"),
             lr.OutlineSection(index=2, title="Scenarios and Probabilities", kiq_ids=["K3"], is_scenario=True)]
BACKEND = Path(__file__).resolve().parents[1]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ================================================================== tool text

def _tools(tmp_path: Path, payload: str, *, absence_on: bool, taxonomy: bool = False):
    calls: list[str] = []

    def search_fn(query: str, n: int) -> str:
        calls.append(query)
        return payload

    ledger = rg.SourceLedger(tmp_path / "sources.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", search_fn=search_fn, fetch_fn=lambda url: "")
    tools.absence_discipline = absence_on
    tools.source_taxonomy = taxonomy
    return tools, calls


NO_RESULT_PAYLOADS = [
    pytest.param(json.dumps({"error": "No results found", "query": "q"}), id="no-results-error"),
    pytest.param(json.dumps({"query": "q", "results": []}), id="empty-results-list"),
    pytest.param(json.dumps({"error": "research_negative_cache_suppressed", "results": []}), id="suppressed-repeat"),
    pytest.param(json.dumps({"results": [{"title": "t", "url": "not-a-url", "content": "c"}]}), id="unusable-rows"),
]


def test_coverage_text_is_no_results_plus_the_absence_sentence():
    assert rg.MSG_NO_RESULTS == "NO_RESULTS: change the entity/angle, not just wording."
    assert rg.MSG_NO_RESULTS_COVERAGE == rg.MSG_NO_RESULTS + COVERAGE_SENTENCE
    assert lr.tool_output_sids("web_search", rg.MSG_NO_RESULTS_COVERAGE) == (None, [])


@pytest.mark.parametrize("payload", NO_RESULT_PAYLOADS)
def test_flag_on_every_empty_search_renders_the_coverage_text_and_stays_cacheable(tmp_path, payload):
    tools, calls = _tools(tmp_path, payload, absence_on=True)
    assert tools.search("some query", agent_id="K1") == rg.MSG_NO_RESULTS_COVERAGE
    assert tools.search("some query", agent_id="K2") == (
        "(cached result; this query was already run)\n" + rg.MSG_NO_RESULTS_COVERAGE)
    assert calls == ["some query"]
    assert tools.stats()["failures"] == 0 and tools.outcome_counts()["search_no_result"] == 1


@pytest.mark.parametrize("payload", NO_RESULT_PAYLOADS)
def test_flag_off_empty_search_keeps_the_no_results_bytes(tmp_path, payload):
    tools, calls = _tools(tmp_path, payload, absence_on=False)
    assert tools.search("some query", agent_id="K1") == rg.MSG_NO_RESULTS
    assert tools.search("some query", agent_id="K1").startswith("(cached result")
    assert calls == ["some query"]


def test_flag_changes_no_other_search_text(tmp_path):
    """Results, outages and the taxonomy's unconfirmed-empty text are the same either way."""
    rows = json.dumps({"results": [{"title": "Capacity", "url": "https://agency.org/r", "content": "176 GW"}]})
    unconfirmed = json.dumps({"error": "No results found", "query": "q", "empty_unconfirmed": True,
                              "provider": "ddg"})
    outage = json.dumps({"error": "Firecrawl HTTP 502", "query": "q"})
    for payload, taxonomy in ((rows, False), (outage, False), (unconfirmed, True)):
        texts = [_tools(tmp_path / f"{flag}-{taxonomy}-{len(payload)}", payload, absence_on=flag,
                        taxonomy=taxonomy)[0].search("q x", agent_id="K1") for flag in (False, True)]
        assert texts[0] == texts[1]
    assert texts[0] == rg.MSG_SEARCH_EMPTY_UNCONFIRMED


# ================================================================== prompt hooks

def _kiq_engine(*, absence_on: bool | None, evidence: str = "off"):
    engine = types.SimpleNamespace(preset=lr.resolve_preset("standard", env={}), language="English",
                                   evidence_mode=evidence)
    if absence_on is not None:
        engine.absence_discipline = absence_on
    engine._kiq_task_addenda = functools.partial(lr._Engine._kiq_task_addenda, engine)
    return engine


def _kiq_task(engine) -> str:
    """The fixed KIQ, seed row and preset of test_research_engine_v3_evidence's pin."""
    kiq = lr.Kiq(id="K1", question="How much data-centre capacity was installed in 2023?",
                 queries=["capacity 2023"], kind="general", why="Sizing the base year.")
    rows = [{"sid": 1, "title": "Official statistics release", "domain": "agency.gov", "tier": "S1",
             "url": "https://agency.gov/r", "snippet": "Capacity reached 176 GW in 2023."}]
    return lr._Engine._kiq_task(engine, kiq, rows)


def _section_engine(*, absence_on: bool | None):
    engine = types.SimpleNamespace(language="English", _section_target=lambda: "about 300 words")
    if absence_on is not None:
        engine.absence_discipline = absence_on
    engine._section_rule_addenda = functools.partial(lr._Engine._section_rule_addenda, engine)
    return engine


def test_rule_texts_are_the_specified_lines():
    assert lr._KIQ_ABSENCE_RULE == KIQ_RULE
    assert lr._SECTION_ABSENCE_RULE == SECTION_RULE


def test_kiq_task_off_is_the_plain_render_and_on_appends_the_absence_line():
    off = _kiq_task(_kiq_engine(absence_on=False))
    assert _sha(off) == KIQ_TASK_SHA256
    assert _kiq_task(_kiq_engine(absence_on=None)) == off          # an engine without the knob
    assert _kiq_task(_kiq_engine(absence_on=True)) == off + "\n" + KIQ_RULE
    # Canonical order: absence (RESEARCH-3) before evidence (RESEARCH-7).
    assert _kiq_task(_kiq_engine(absence_on=True, evidence="audit")) == (
        off + "\n" + KIQ_RULE + "\n" + lr._KIQ_EVIDENCE_RULE)
    assert _kiq_task(_kiq_engine(absence_on=False, evidence="audit")) == off + "\n" + lr._KIQ_EVIDENCE_RULE


@pytest.mark.parametrize("kwargs, pinned", [
    ({}, SECTION_TASK_SHA256),
    ({"note": "Fix the citation.", "current": "Old body [S1]."}, SECTION_REWRITE_TASK_SHA256),
])
def test_section_task_off_is_byte_identical_and_on_adds_the_rule_after_the_rules(kwargs, pinned):
    off = lr._Engine.section_task(_section_engine(absence_on=False), _SECTIONS, **kwargs)
    assert _sha(off) == pinned
    assert lr._Engine.section_task(_section_engine(absence_on=None), _SECTIONS, **kwargs) == off
    on = lr._Engine.section_task(_section_engine(absence_on=True), _SECTIONS, **kwargs)
    assert lr._SECTION_RULES + "\n" + SECTION_RULE in on
    assert on.replace(lr._SECTION_RULES + "\n" + SECTION_RULE, lr._SECTION_RULES, 1) == off


# ================================================================== absence cues

@pytest.mark.parametrize("text, cue", [
    ("No talks have been reported between the two ministries.", "No talks have been reported"),
    ("The merger has not been announced.", "has not been announced"),
    ("There is no evidence that the plant closed.", "There is no evidence"),
    ("Officials have not yet confirmed the date.", "have not yet confirmed"),
    ("The regulator hasn't disclosed the fine.", "hasn't disclosed"),
    ("There were no official records of the meeting.", "There were no official records"),
    ("So far there has been no public announcement.", "there has been no public announcement"),
    ("No official agreement was signed.", "No official agreement"),
    ("双方尚未宣布停火协议。", "尚未宣布"),
    ("目前暂无公开报道。", "暂无公开报道"),
    ("市场上未见报道。", "未见报道"),
    ("公司尚未正式确认该计划。", "尚未正式确认"),
    # A comparison, "not only" or "no doubt" in the same clause does not undo a real claim.
    ("Growth of no more than 5% has not been confirmed.", "has not been confirmed"),
    ("Shares rose no more than 5% after the merger had not been confirmed.", "had not been confirmed"),
    ("Output of no less than 3 GW has not been confirmed by the ministry.", "has not been confirmed"),
    ("Not only has no official agreement been signed, talks have stalled.", "no official agreement"),
    ("There is no doubt the plan has not been disclosed.", "has not been disclosed"),
    # A clause break (punctuation or a joining conjunction) ends a scope exclusion's reach.
    ("The date is unlikely to change; officials have not confirmed it.", "have not confirmed"),
    ("The firm won't comment and has not disclosed the fee.", "has not disclosed"),
    ("The regulator will not rule until June but has not confirmed a date.", "has not confirmed"),
])
def test_absence_cue_hits(text, cue):
    assert lr.absence_cue(text) == cue


@pytest.mark.parametrize("text", [
    # No cue branch reads an exclusion phrase.
    "no longer",
    "no more than 5%",
    "no less than",
    "not only",
    "no doubt",
    "will not",
    "won't",
    "is unlikely to",
    "Operators no longer publish quarterly capacity figures.",
    "Growth of no more than 5% was reported in 2023.",
    "Not only has capacity grown, it has accelerated.",
    "The regulator will not approve the plan this year.",
    "The plan is unlikely to be announced before May.",
    "The deal has been announced and reported widely.",
    "There is no doubt that capacity rose.",
    # A scope exclusion in the cue's own clause lead-in disqualifies it.
    "It is no longer true that no deal has been announced.",
    "Officials will not say whether there is no evidence of a leak.",
    "Officials won't confirm that there is no official record.",
    "The ministry is unlikely to say there is no evidence.",
    "预计明年将公布数据。",
    "",
])
def test_absence_cue_misses(text):
    assert lr.absence_cue(text) is None


def test_absence_cue_scope_exclusion_can_drop_a_real_claim():
    """The documented trade-off: a scope exclusion disqualifies every later cue in
    its clause, a factive one included, so absence_findings is a lower bound."""
    assert lr.absence_cue("It will not matter that there is no public evidence") is None


def test_absence_cue_rejects_non_strings_and_scans_past_an_excluded_cue():
    assert lr.absence_cue(None) is None and lr.absence_cue(42) is None
    text = "It is no longer true that no official deal exists; the plan has not been disclosed."
    assert lr.absence_cue(text) == "has not been disclosed"
    assert lr.absence_cue("has\n\n  not   been \t announced") == "has not been announced"


@pytest.mark.parametrize("unit", [
    "no ", "has ", "have not ", "there is no ", "no reported ", "尚未", "暂无公开", "a", " \n",
    "no doubt has not been announced ", "not only there is no evidence ",
    "won't say there is no evidence and ", "is unlikely to, ",
])
def test_absence_cue_is_linear_on_adversarial_input(unit):
    text = (unit * (200_000 // len(unit) + 1))[:200_000]
    started = time.perf_counter()
    lr.absence_cue(text)
    assert time.perf_counter() - started < 0.5


def test_absence_cue_counts_by_tag():
    facts = [{"text": "No talks have been reported [S1]", "tag": "REPORTED"},
             {"text": "The deal has not been confirmed [S2]", "tag": "VERIFIED"},
             {"text": "暂无公开报道 [S3]", "tag": "UNVERIFIED"},
             {"text": "Capacity reached 176 GW [S1]", "tag": "VERIFIED"},
             "not a fact"]
    assert lr.absence_cue_counts(facts) == {"VERIFIED": 1, "REPORTED": 1, "UNVERIFIED": 1}
    assert lr.absence_cue_counts([]) == {"VERIFIED": 0, "REPORTED": 0, "UNVERIFIED": 0}


def test_absence_cue_counts_keep_the_tag_shape():
    """A fact with an unknown, missing or unhashable tag is not counted, so the
    record and meta keys are always exactly the three evidence tags."""
    cue = "The deal has not been confirmed [S1]"
    facts = [{"text": cue, "tag": "WEIRD"}, {"text": cue}, {"text": cue, "tag": ""},
             {"text": cue, "tag": ["VERIFIED"]}, {"text": cue, "tag": "REPORTED"}]
    assert lr.absence_cue_counts(facts) == {"VERIFIED": 0, "REPORTED": 1, "UNVERIFIED": 0}


def test_absence_cue_count_failure_degrades_safe(monkeypatch):
    def broken(_facts):
        raise RuntimeError("regex engine exploded")

    monkeypatch.setattr(lr, "absence_cue_counts", broken)
    logged: list[tuple[str, str]] = []
    engine = types.SimpleNamespace(analytics_errors=[], log=lambda kind, message: logged.append((kind, message)))
    assert lr._Engine._absence_cues(engine, "K1", [{"text": "x", "tag": "REPORTED"}]) is None
    assert engine.analytics_errors == [{"helper": "absence_cues", "kiq": "K1",
                                        "error": "RuntimeError: regex engine exploded"}]
    assert logged and logged[0][0] == "warn"


# ================================================================== engine run

ABSENT_TALKS = "No talks have been reported between the grid operators and the regulator"
ABSENT_TARGET = "The regulator has not yet confirmed a 250 GW national target for 2030"
NOT_ABSENT = "Operators no longer publish quarterly capacity figures"
_ORIGINAL_SEARCH = v3.fake_search


class AbsenceWorld(v3.World):
    """Each KIQ's notes add two absence findings and a lookalike that is not one."""

    def notes(self, tool_results) -> str:
        notes = super().notes(tool_results)
        cite = re.search(r"\[S(\d+)\]", notes).group(1)
        extra = [f"- {ABSENT_TALKS} [S{cite}] (REPORTED)", f"- {ABSENT_TARGET} [S{cite}] (VERIFIED)",
                 f"- {NOT_ABSENT} [S{cite}] (REPORTED)"]
        return notes.replace("## Findings\n", "## Findings\n" + "\n".join(extra) + "\n", 1)


def _sparse_search(query: str, n: int) -> str:
    """The agents' second search ("<KIQ> market outlook") finds nothing."""
    if "market outlook" in query:
        return json.dumps({"query": query, "results": []})
    return _ORIGINAL_SEARCH(query, n)


def _records(out: Path) -> dict[str, dict]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((out / "v3" / "kiq").glob("*.json"))}


def _tool_texts(model) -> list[str]:
    return [content for call in model.calls for kind, content in call["messages"] if kind == "tool"]


def _last_messages(model, role: str) -> list[str]:
    return [call["messages"][-1][1] for call in v3.calls_of(model, role)]


def _kiq_tasks(model) -> set[str]:
    return {call["messages"][2][1] for call in v3.calls_of(model, "agent") if len(call["messages"]) == 3}


def test_engine_run_counts_absence_findings_and_changes_no_tag(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")   # deterministic runs: the prompts compare
    monkeypatch.setattr(v3, "fake_search", _sparse_search)
    rc, meta_off, _, model_off, out_off = v3.run_engine(tmp_path, bridge, AbsenceWorld(), out_dir=tmp_path / "off")
    assert rc == 0 and meta_off["status"] == "completed"
    monkeypatch.setenv("RESEARCH_ABSENCE_DISCIPLINE", "true")
    rc, meta_on, _, model_on, out_on = v3.run_engine(tmp_path, bridge, AbsenceWorld(), out_dir=tmp_path / "on")
    assert rc == 0 and meta_on["status"] == "completed"

    # Off: no absence line, text, record key or meta key anywhere.
    off_tools = _tool_texts(model_off)
    assert rg.MSG_NO_RESULTS in off_tools and not any(COVERAGE_SENTENCE in text for text in off_tools)
    assert not any(KIQ_RULE in task for task in _kiq_tasks(model_off))
    off_writers = _last_messages(model_off, "SECTION WRITING TASK")
    assert off_writers and not any(SECTION_RULE in task for task in off_writers)
    records_off = _records(out_off)
    assert records_off and all("absence_cues" not in record for record in records_off.values())
    meta_file_off = json.loads((out_off / "meta.json").read_text(encoding="utf-8"))
    assert "absence_findings" not in meta_off and "absence_findings" not in meta_file_off

    # On: the tool text and both prompt lines; ENGINE_CORE and the brief are unchanged.
    on_tools = _tool_texts(model_on)
    assert rg.MSG_NO_RESULTS_COVERAGE in on_tools and rg.MSG_NO_RESULTS not in on_tools
    on_tasks = _kiq_tasks(model_on)
    assert on_tasks and all(task.endswith("\n" + KIQ_RULE) for task in on_tasks)
    assert {task[:-len(KIQ_RULE) - 1] for task in on_tasks} == _kiq_tasks(model_off)
    on_writers = _last_messages(model_on, "SECTION WRITING TASK")
    assert on_writers and all(lr._SECTION_RULES + "\n" + SECTION_RULE in task for task in on_writers)
    assert sorted(task.replace("\n" + SECTION_RULE, "", 1) for task in on_writers) == sorted(off_writers)
    assert {call["messages"][0][1] for call in model_on.calls} == {lr.ENGINE_CORE}
    assert {call["messages"][1][1] for call in model_on.calls if len(call["messages"]) > 2} == \
        {call["messages"][1][1] for call in model_off.calls if len(call["messages"]) > 2}

    # Observe only: the same facts and tags; the absence findings are counted by tag.
    records_on = _records(out_on)
    assert [record["facts"] for record in records_on.values()] == [record["facts"] for record in records_off.values()]
    total: Counter[str] = Counter()
    for kid, record in records_on.items():
        cued = Counter(fact["tag"] for fact in records_off[kid]["facts"]
                       if fact["text"].startswith((ABSENT_TALKS, ABSENT_TARGET)))
        assert sum(cued.values()) == 2
        assert any(fact["text"].startswith(NOT_ABSENT) for fact in record["facts"])
        assert record["absence_cues"] == {"VERIFIED": cued["VERIFIED"], "REPORTED": cued["REPORTED"],
                                          "UNVERIFIED": cued["UNVERIFIED"]}
        total.update(cued)
    expected = {"total": 2 * len(records_on), "VERIFIED": total["VERIFIED"], "REPORTED": total["REPORTED"],
                "UNVERIFIED": total["UNVERIFIED"]}
    assert meta_on["absence_findings"] == expected
    assert json.loads((out_on / "meta.json").read_text(encoding="utf-8"))["absence_findings"] == expected


# ================================================================== market status, knob

def test_market_status_maps_the_explicit_partial_transport_label_to_unavailable():
    """RESEARCH-3's bridge label: coverage unknown, never an empty market finding
    (before the mapping the no_relevant_markets marker made it 'empty')."""
    payload = {"markets": [], "no_relevant_markets": True,
               "status": {"attempted": True, "empty_reason": "partial_transport_failure"}}
    status = absence.market_status(payload, enabled=True)
    assert (status.state, status.reason) == ("unavailable", "partial_transport_failure")


def test_knob_defaults_off_and_is_forwarded_to_the_v3_child_only():
    assert ("RESEARCH_ABSENCE_DISCIPLINE", "bool") in po.RESEARCH_CHILD_V3_KNOBS
    assert all(name != "RESEARCH_ABSENCE_DISCIPLINE" for name, _kind in po.RESEARCH_CHILD_KNOBS)
    env = {key: value for key, value in os.environ.items() if key != "RESEARCH_ABSENCE_DISCIPLINE"}
    env["DRF_TEST_PROCESS"] = "1"
    probe = subprocess.run([sys.executable, "-c", "from app.config import Config; "
                            "print(repr(Config.RESEARCH_ABSENCE_DISCIPLINE))"],
                           cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60, check=True)
    assert probe.stdout.strip().splitlines()[-1] == "False"
    env_example = (BACKEND.parent / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^# RESEARCH_ABSENCE_DISCIPLINE=false\s+# ", env_example, re.M)
