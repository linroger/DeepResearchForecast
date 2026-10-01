"""REPORT-13 (C09): the evidence-cited counter-case pass, module level (forecast_counter_case).

One strong-tier call over a byte-stable [S#] evidence packet; deterministic claim walls
(unknown_source / uncited / unverified_number / source_mismatch, undecidable support kept
as unverifiable); claim ids written by code; dated or thresholded triggers with an admissible
[S#]; failures degrade to status 'failed' with no outputs. Offline: FakeLLMClient and stub
support checks, plus ReportAgent's real support check and number extractor where noted.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from collections import Counter

import pytest

from app.services import forecast_counter_case as fc
from app.services.report_agent import ReportAgent
from app.utils.telemetry import BudgetExceeded
from tests.conftest import FakeLLMClient

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NUMBERS = ReportAgent._semantic_numbers


def _support_by_row(text, source):
    """Stub support check: each source row carries the verdict it returns."""
    return source["verdict"]


STUB_TAGS = {
    "S1": {"title": "a", "url": "https://a.example/1", "verdict": True},
    "S2": {"title": "b", "url": "https://b.example/2", "verdict": False},
    "S3": {"title": "c", "url": "https://c.example/3", "verdict": None},
    "S4": {"title": "d", "url": "https://d.example/4", "verdict": True},
    "S5": {"title": "e", "url": "https://e.example/5", "verdict": True},
}

REAL_TAGS = {
    "S1": {"title": "Global EV Outlook", "url": "https://iea.example/ev",
           "supports": ["Global electric car sales reached 17 million units in 2024, led by China."]},
    "S2": {"title": "Battery price survey", "url": "https://bnef.example/battery",
           "supports": ["Average lithium-ion pack prices fell to 115 dollars per kilowatt-hour."]},
    "S3": {"title": "Grid connection queue", "url": "https://grid.example/queue",
           "supports": ["Interconnection queues lengthened across most regional grids."]},
}

SPINE = {"scenarios": [
    {"name": "Upside path", "probability": 0.45,
     "resolution_criteria": "Electric car sales exceed 25 million units in 2027"},
    {"name": "Downside path", "probability": 0.25,
     "resolution_criteria": "Battery pack prices stop falling before 2027"},
    {"name": "Grid bottleneck", "probability": 0.15,
     "resolution_criteria": "Interconnection queues delay charging rollout"},
    {"name": "Other / Status Quo", "probability": 0.15, "resolution_criteria": "Anything else"},
]}


def _claims(raw, *, side="higher", tags=STUB_TAGS, numbers=("17", "250"), support=_support_by_row):
    return fc.validate_claims(raw, target_id="T1", side=side, tag_map=tags,
                              packet_numbers=frozenset(numbers), support_fn=support,
                              numbers_fn=NUMBERS)


# ---------------------------------------------------------------- claim walls

def test_claim_walls():
    kept, dropped = _claims([
        {"text": "Sales hit a record high [S99]"},                                  # unknown_source
        {"text": "Sales hit a record high", "sources": ["S1", "S99"]},              # unknown_source
        {"text": "Sales are clearly accelerating"},                                 # uncited
        {"text": "The share should be 35% by then", "sources": ["S1"]},             # percent
        {"text": "Adoption should rise by 35 percent", "sources": ["S1"]},          # percent words
        {"text": "提升百分之三十", "sources": ["S1"]},                                 # 百分之
        {"text": "Sales reached 42 million units", "sources": ["S1"]},              # 42 not in packet
        {"text": "A 0.35 chance looks too low", "sources": ["S1"]},                 # decimal not in packet
        {"text": "Pack prices are not falling as claimed", "sources": ["S2"]},      # all False
        {"text": "Mixed support stays undecided", "sources": ["S2", "S3"]},         # False + None
    ])
    assert dropped == Counter({"unknown_source": 2, "uncited": 1, "unverified_number": 5,
                               "source_mismatch": 1})
    assert [(c["id"], c["verdict"], c["sources"]) for c in kept] == [
        ("T1.H1", "unverifiable", ["S2", "S3"])]

    kept, dropped = _claims([
        {"text": "Sales reached 17 million units in 2030 after 3 good years", "sources": ["S1"]},
        {"text": "Undecidable cross-language support [S3]"},                         # None -> kept
        {"text": "One supporting source is enough", "sources": ["S2", "S4"]},
    ], side="lower")
    assert not dropped
    assert [(c["id"], c["verdict"]) for c in kept] == [
        ("T1.L1", "valid"), ("T1.L2", "unverifiable"), ("T1.L3", "valid")]
    assert kept[1]["text"] == "Undecidable cross-language support" and kept[1]["sources"] == ["S3"]


def test_claim_caps():
    long_text = "Sales keep growing across every major market " * 20
    kept, dropped = _claims([
        {"text": long_text, "sources": ["S1", "S2", "S3", "S4", "S5"]},
        {"text": "Second valid claim", "sources": ["[S4]"]},
        {"text": "Third valid claim", "sources": [5]},
        {"text": "Fourth valid claim", "sources": ["S1"]},
        {"text": "Fifth valid claim", "sources": ["S1"]},
    ])
    assert len(kept) == 3 and dropped == Counter({"over_cap": 2})
    assert len(kept[0]["text"]) <= fc.MAX_CLAIM_CHARS and kept[0]["text"].endswith("…")
    assert kept[0]["sources"] == ["S1", "S2", "S3", "S4"]          # at most four sources
    assert [c["sources"] for c in kept[1:]] == [["S4"], ["S5"]]    # markers normalised
    # Malformed and empty items are counted, never kept.
    kept, dropped = _claims([42, {"text": "  "}, None])
    assert kept == [] and dropped == Counter({"malformed": 2, "empty": 1})


def test_claim_walls_with_the_report_support_check():
    support = ReportAgent._semantic_citation_support
    kept, dropped = _claims([
        {"text": "Global electric car sales reached 17 million units in 2024, led by China.",
         "sources": ["S1"]},
        {"text": "Interconnection queues across regional grids keep the rollout slow.",
         "sources": ["S1"]},
    ], tags=REAL_TAGS, support=support)
    assert [(c["id"], c["verdict"]) for c in kept] == [("T1.H1", "valid")]
    assert dropped == Counter({"source_mismatch": 1})


# ---------------------------------------------------------------- targets, ids, names

def test_select_targets():
    targets = fc.select_targets(SPINE)
    assert [(t["target_id"], t["scenario"]) for t in targets] == [
        ("T1", "Upside path"), ("T2", "Downside path"), ("T3", "Grid bottleneck")]
    spine = {"scenarios": [
        {"name": "Zeta", "probability": 0.3}, {"name": "Alpha", "probability": 0.3},
        {"name": "基准情景", "probability": 0.2}, {"name": "其他情形", "probability": 0.1},
        {"name": "维持现状", "probability": 0.05}, {"name": "Another wave", "probability": 0.04},
        {"name": "Unreadable", "probability": "high"}, {"name": "Others", "probability": 0.5}]}
    assert [t["scenario"] for t in fc.select_targets(spine, k=4)] == [
        "Alpha", "Zeta", "基准情景", "Another wave"]
    assert fc.select_targets({"scenarios": []}) == [] and fc.select_targets(None) == []


def _packet(tags=REAL_TAGS, **over):
    kwargs = {
        "sources_index": "[S1] Global EV Outlook\n[S2] Battery price survey\n[S3] Grid connection queue",
        "tag_map": tags,
        "research_report": (
            "## Demand\n\nGlobal electric car sales reached 17 million units in 2024 [S1].\n\n"
            "## Costs\n\nPack prices fell to 115 dollars per kilowatt-hour [S2]."),
        "contested_block": "", "market_pack": "", "spine": SPINE,
        "question": "Will EV sales keep rising?", "cap": 12000, "numbers_fn": NUMBERS}
    kwargs.update(over)
    return fc.build_evidence_packet(**kwargs)


REPLY = {"targets": [
    {"scenario": "upside PATH.", "id": "X9", "speaker": "bull", "role": "judge",
     "case_for_higher": [
         {"id": "bull-1", "speaker": "bull", "role": "advocate",
          "text": "Global electric car sales reached 17 million units in 2024, led by China.",
          "sources": ["S1"]}],
     "case_for_lower": [
         {"text": "Interconnection queues lengthened across most regional grids.", "sources": ["S3"],
          "id": "bear-7"}],
     "what_would_change": [
         {"signal": "Annual EV sales", "direction": "raises", "threshold_or_event": "above 25 million",
          "by": "2027-12-31", "sources": ["S1"]}]},
    {"scenario": "Imaginary path",
     "case_for_higher": [{"text": "Global electric car sales reached 17 million units in 2024.",
                          "sources": ["S1"]}]},
    {"scenario": "Downside path",
     "case_for_lower": [{"text": "Average lithium-ion pack prices fell to 115 dollars per kilowatt-hour.",
                         "sources": ["S2"]}]},
]}


def _run(reply=REPLY, llm=None, **over):
    llm = llm or FakeLLMClient(json_responses=[json.loads(json.dumps(reply))])
    packet = _packet()
    kwargs = {"llm": llm, "packet": packet, "tag_map": REAL_TAGS,
              "support_fn": ReportAgent._semantic_citation_support, "numbers_fn": NUMBERS,
              "question": "Will EV sales keep rising?", "lang": "English"}
    kwargs.update(over)
    return fc.run_counter_case(SPINE, **kwargs), llm, packet


def test_code_assigned_ids():
    result, llm, packet = _run()
    assert result["status"] == "complete" and result["schema"] == "drf.counter_case/v1"
    assert result["packet_sha256"] == packet["sha256"]
    (call,) = llm.calls
    assert call["kind"] == "chat_json" and call["temperature"] == 0.1
    assert call["max_tokens"] == 3000 and call["tier"] is None
    system, user = call["messages"]
    assert system["role"] == "system" and system["content"].endswith(packet["text"])
    assert '"Upside path" (stated 45%)' in user["content"] and "Other / Status Quo" not in user["content"]
    t1, t2, t3 = result["targets"]
    assert (t1["target_id"], t1["scenario"], t1["probability"]) == ("T1", "Upside path", 0.45)
    assert t1["claims"]["higher"] == [{
        "id": "T1.H1", "sources": ["S1"], "verdict": "valid",
        "text": "Global electric car sales reached 17 million units in 2024, led by China."}]
    assert [c["id"] for c in t1["claims"]["lower"]] == ["T1.L1"]
    assert [c["id"] for c in t2["claims"]["lower"]] == ["T2.L1"] and t2["claims"]["higher"] == []
    # "Imaginary path" matched no target: its claim reached nobody; T3 got nothing at all.
    assert t3["claims"] == {"higher": [], "lower": []} and t3["triggers"] == []
    blob = json.dumps(result)
    assert not any(token in blob for token in ("X9", "bull", "bear-7", "advocate", "judge", "speaker"))
    for claims in (t["claims"] for t in result["targets"]):
        for claim in claims["higher"] + claims["lower"]:
            assert set(claim) == {"id", "text", "sources", "verdict"}


# ---------------------------------------------------------------- packet

def test_packet():
    a, b = _packet(), _packet()
    assert a["text"] == b["text"] and a["sha256"] == b["sha256"]
    assert _packet(market_pack="Market X 40%")["sha256"] != a["sha256"]
    text = a["text"]
    assert text.startswith(fc.PACKET_BEGIN + "\n=== SOURCE INDEX ===") and text.endswith(fc.PACKET_END)
    order = [text.index(h) for h in ("=== SOURCE INDEX ===", "=== DOSSIER EXCERPTS ===",
                                     "=== CONTESTED CLAIMS ===",
                                     "=== MARKET ANCHORS (calibration anchors, not truth) ===")]
    assert order == sorted(order)
    assert "(No contested-claims table in this run: not available, not an empty finding.)" in text
    assert "(No prediction-market anchors in this run: not available, not an empty finding.)" in text
    assert "17" in a["numbers"] and "115" in a["numbers"] and "2024" not in a["numbers"]
    # No simulation input exists on the packet's surface at all.
    params = set(inspect.signature(fc.build_evidence_packet).parameters)
    assert not any("signal" in p or "sim" in p for p in params)
    with_blocks = _packet(contested_block="## Contested\n- Claim A — side [S2]",
                          market_pack="Polymarket: EV sales above 20 million — 40%")["text"]
    assert "- Claim A — side [S2]" in with_blocks and "Polymarket: EV sales" in with_blocks
    assert fc.ABSENT_CONTESTED not in with_blocks and fc.ABSENT_MARKET not in with_blocks


def test_packet_excerpts_only_admissible_cited_paragraphs():
    report = "\n\n".join([
        "# Dossier",
        "Opening paragraph without any marker about electric car sales.",
        "Electric car sales reached 17 million units [S1].",
        "A claim citing a source outside the index [S9].",
        "Grid queues lengthened, slowing the rollout of chargers [S3].",
        "## References",
        "- [S1] Global EV Outlook — https://iea.example/ev\n- [S2] Battery price survey",
    ])
    text = _packet(research_report=report)["text"]
    dossier = text.split("=== DOSSIER EXCERPTS ===\n", 1)[1].split("\n\n=== CONTESTED", 1)[0]
    assert dossier == ("Electric car sales reached 17 million units [S1].\n\n"
                       "Grid queues lengthened, slowing the rollout of chargers [S3].")
    # With room for one paragraph, the one overlapping the question/scenarios most wins.
    small = _packet(research_report=report, cap=70, spine=None,
                    question="grid interconnection queues")["text"]
    assert "Grid queues lengthened" in small and "17 million units [S1]" not in small
    # Selected paragraphs keep document order even when a later one ranks higher.
    spine = {"scenarios": [{"name": "Electric sales", "probability": 0.5}]}
    both = _packet(research_report=report, spine=spine, question="grid queues rollout")["text"]
    assert both.index("17 million units") < both.index("Grid queues lengthened")
    empty = _packet(research_report="No markers here.")["text"]
    assert fc.ABSENT_DOSSIER in empty
    # Paragraphs are cut at 1200 characters before the marker check: a marker beyond the cut
    # does not make the paragraph cited.
    head = "[S1] " + "Electric car sales grew. " * 80
    tail = "Battery prices fell. " * 80 + "[S2]"
    cut = _packet(research_report=head + "\n\n" + tail, spine=None)["text"]
    dossier = cut.split("=== DOSSIER EXCERPTS ===\n", 1)[1].split("\n\n=== CONTESTED", 1)[0]
    assert dossier.startswith("[S1] Electric car sales grew.") and dossier.endswith("…")
    assert len(dossier) <= fc.PARAGRAPH_CHARS and "Battery prices fell" not in dossier


# ---------------------------------------------------------------- triggers

def _trigger(**over):
    row = {"signal": "Annual EV sales", "direction": "raises",
           "threshold_or_event": "above 25 million", "by": "", "sources": ["S1"]}
    row.update(over)
    return row


def test_triggers():
    kept = fc.validate_triggers([
        _trigger(threshold_or_event="a policy shift"),                          # no digit, no date
        _trigger(threshold_or_event="a policy shift", by="2027-13-45"),         # invalid date
        _trigger(threshold_or_event="a policy shift", by="2027-06-30"),         # date -> kept
        _trigger(sources=["S99"]),                                              # no valid [S#]
        _trigger(sources=[]),                                                   # uncited
        _trigger(direction="up"),                                               # bad direction
        _trigger(signal="  "),                                                  # empty signal
        _trigger(sources=["S99", "[S2]"], by="Q3 2027"),                        # S2 kept, by -> ''
        "not a trigger",
    ], REAL_TAGS)
    assert kept == [
        {"signal": "Annual EV sales", "direction": "raises", "threshold_or_event": "a policy shift",
         "by": "2027-06-30", "sources": ["S1"]},
        {"signal": "Annual EV sales", "direction": "raises", "threshold_or_event": "above 25 million",
         "by": "", "sources": ["S2"]},
    ]
    # At most three per target.
    assert len(fc.validate_triggers([_trigger() for _ in range(5)], REAL_TAGS)) == 3


def test_triggers_total_cap(monkeypatch):
    monkeypatch.setattr(fc, "MAX_TARGETS", 4)
    spine = {"scenarios": [{"name": f"Path {n}", "probability": 0.25} for n in "ABCD"]}
    reply = {"targets": [{"scenario": f"Path {n}", "what_would_change": [_trigger() for _ in range(5)]}
                         for n in "ABCD"]}
    llm = FakeLLMClient(json_responses=[reply])
    result = fc.run_counter_case(spine, llm=llm, packet=_packet(), tag_map=REAL_TAGS,
                                 support_fn=ReportAgent._semantic_citation_support,
                                 numbers_fn=NUMBERS, question="q", lang="English")
    assert [len(t["triggers"]) for t in result["targets"]] == [3, 3, 3, 1]
    assert result["triggers_dropped"] == 20 - 10
    rows = fc.triggers_to_indicators(result)
    assert len(rows) == 10
    assert rows[0] == {"indicator": "Annual EV sales", "date_or_trigger": "above 25 million",
                       "discriminates": "Path A", "source": "counter_case", "sources": ["S1"],
                       "direction": "raises", "threshold_or_event": "above 25 million"}


# ---------------------------------------------------------------- failure

class _RaisingLLM(FakeLLMClient):
    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier, **kwargs)
        raise self._exc


@pytest.mark.parametrize("exc", [RuntimeError("provider down"), BudgetExceeded("budget spent")])
def test_failure_degrades(exc):
    result, llm, _ = _run(llm=_RaisingLLM(exc))
    assert len(llm.calls) == 1
    assert result["status"] == "failed" and type(exc).__name__ in result["error"]
    assert result["targets"] == [] and fc.triggers_to_indicators(result) == []
    assert fc.render_counter_case_block(result, "English") == ""


@pytest.mark.parametrize("reply", [[], {"targets": "none"}, {"answer": 1}])
def test_malformed_reply_fails(reply):
    result, _, _ = _run(llm=FakeLLMClient(json_responses=[reply]))
    assert result["status"] == "failed" and "targets" in result["error"]
    assert fc.triggers_to_indicators(result) == []


def test_base_exceptions_propagate():
    from app.services.pipeline_orchestrator import PipelineCancelled
    with pytest.raises(PipelineCancelled):
        _run(llm=_RaisingLLM(PipelineCancelled("cancelled")))


def test_skipped_without_targets_or_sources():
    llm = FakeLLMClient()
    result = fc.run_counter_case({"scenarios": [{"name": "Other", "probability": 1.0}]}, llm=llm,
                                 packet=_packet(), tag_map=REAL_TAGS, support_fn=_support_by_row,
                                 numbers_fn=NUMBERS, question="q", lang="English")
    assert (result["status"], result["reason"]) == ("skipped", "no_targets")
    result, llm, _ = _run(llm=llm, tag_map={"S1-a": REAL_TAGS["S1"]})
    assert (result["status"], result["reason"]) == ("skipped", "no_admissible_sources")
    assert llm.calls == []


# ---------------------------------------------------------------- renderers

def test_render_block_and_summary():
    result, _, _ = _run()
    block = fc.render_counter_case_block(result, "English")
    assert block == (
        '- T1 "Upside path"\n'
        "  - Case for higher: Global electric car sales reached 17 million units in 2024, "
        "led by China. [S1]\n"
        "  - Case for lower: Interconnection queues lengthened across most regional grids. [S3]\n"
        '- T2 "Downside path"\n'
        "  - Case for lower: Average lithium-ion pack prices fell to 115 dollars per "
        "kilowatt-hour. [S2]")
    zh = fc.render_counter_case_block(result, "Chinese")
    assert zh.startswith("- T1 「Upside path」\n  - 上调理由：Global electric car sales")
    assert fc.render_counter_case_block(result, "English", max_chars=50) == ""
    # The first valid claim of a side wins; an unverifiable one is used (labelled) only without one.
    target = {"target_id": "T1", "scenario": "A", "claims": {
        "higher": [{"text": "U", "sources": ["S3"], "verdict": "unverifiable"},
                   {"text": "V", "sources": ["S1"], "verdict": "valid"}],
        "lower": [{"text": "W", "sources": ["S3"], "verdict": "unverifiable"}]}}
    custom = fc.render_counter_case_block({"status": "complete", "targets": [target]}, "English")
    assert custom == ('- T1 "A"\n  - Case for higher: V [S1]\n'
                      "  - Case for lower: W [S3] (source support not machine-verified)")
    summary = fc.forecast_summary(result, "abc")
    assert summary == {"schema": "drf.counter_case/v1", "status": "complete",
                       "artifact": "counter_case.json", "artifact_sha256": "abc",
                       "claims_valid": 3, "claims_unverifiable": 0, "claims_dropped": 0,
                       "triggers": 1}
    text = fc.artifact_text(result)
    assert json.loads(text) == result and text == json.dumps(result, ensure_ascii=False,
                                                             sort_keys=True, indent=2)


def test_merge_indicators_dedupes_by_casefolded_text():
    research = [{"indicator": "Annual EV Sales", "date_or_trigger": "2026-Q4"}]
    counter = [{"indicator": "annual ev sales ", "source": "counter_case"},
               {"indicator": "Pack prices", "source": "counter_case"},
               {"indicator": "PACK PRICES", "source": "counter_case"}]
    merged = fc.merge_indicators(research, counter)
    assert merged == research + [{"indicator": "Pack prices", "source": "counter_case"}]
    assert fc.merge_indicators(research, []) == research


# ---------------------------------------------------------------- knobs

_DEFAULTS_CHILD = r"""
import json, os
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
for key in ("REPORT_COUNTER_CASE", "REPORT_COUNTER_CASE_EVIDENCE_CHARS"):
    os.environ.pop(key, None)
from app.config import Config
print("<<<JSON>>>" + json.dumps([Config.REPORT_COUNTER_CASE, Config.REPORT_COUNTER_CASE_EVIDENCE_CHARS]))
"""


def test_knob_defaults_and_documentation():
    names = ("REPORT_COUNTER_CASE", "REPORT_COUNTER_CASE_EVIDENCE_CHARS")
    env = {key: value for key, value in os.environ.items() if key not in names}
    proc = subprocess.run([sys.executable, "-c", _DEFAULTS_CHILD], cwd=_BACKEND, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    [payload] = [line for line in proc.stdout.splitlines() if line.startswith("<<<JSON>>>")]
    assert json.loads(payload[len("<<<JSON>>>"):]) == [False, 12000]
    with open(os.path.join(os.path.dirname(_BACKEND), ".env.example"), encoding="utf-8") as handle:
        text = handle.read()
    for line in ("# REPORT_COUNTER_CASE=false ", "# REPORT_COUNTER_CASE_EVIDENCE_CHARS=12000 "):
        assert line in text
