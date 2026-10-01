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
from datetime import date, datetime

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
    "S6": {"title": "f", "url": "https://f.example/6", "verdict": None},
    "S7": {"title": "g", "url": "https://g.example/7", "verdict": None},
    "S8": {"title": "h", "url": "https://h.example/8", "verdict": None},
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
        {"text": "Sales hit a record high", "sources": ["S1", "S4", "S5", "S6", "S99"]},  # 5th place
        {"text": "Sales are clearly accelerating"},                                 # uncited
        {"text": "The share should be 35% by then", "sources": ["S1"]},             # percent
        {"text": "Adoption should rise by 35 percent", "sources": ["S1"]},          # percent words
        {"text": "提升百分之三十", "sources": ["S1"]},                                 # 百分之
        {"text": "A thirty percent chance is too low", "sources": ["S1"]},          # no digit
        {"text": "七成概率会继续增长", "sources": ["S1"]},                              # tenths
        {"text": "Only one in three buyers can charge at home", "sources": ["S1"]},  # odds
        {"text": "Sales reached 42 million units", "sources": ["S1"]},              # 42 not in packet
        {"text": "A 0.35 chance looks too low", "sources": ["S1"]},                 # decimal not in packet
        {"text": "Pack prices are not falling as claimed", "sources": ["S2"]},      # all False
        {"text": "Mixed support stays undecided", "sources": ["S2", "S3"]},         # False + None
    ])
    assert dropped == Counter({"unknown_source": 3, "uncited": 1, "unverified_number": 8,
                               "source_mismatch": 1, fc.TAG_DROP_KEY: 1})
    # The contradicted S2 is removed; the undecided S3 keeps the claim as unverifiable.
    assert [(c["id"], c["verdict"], c["sources"]) for c in kept] == [
        ("T1.H1", "unverifiable", ["S3"])]

    kept, dropped = _claims([
        {"text": "Sales reached 17 million units in 2030 after 3 good years", "sources": ["S1"]},
        {"text": "Undecidable cross-language support [S3]"},                         # None -> kept
        {"text": "One supporting source is enough", "sources": ["S2", "S4"]},
    ], side="lower")
    assert dropped == Counter({fc.TAG_DROP_KEY: 1})
    assert [(c["id"], c["verdict"], c["sources"]) for c in kept] == [
        ("T1.L1", "valid", ["S1"]), ("T1.L2", "unverifiable", ["S3"]), ("T1.L3", "valid", ["S4"])]
    assert kept[1]["text"] == "Undecidable cross-language support"


def test_probabilities_in_words_are_unverified_numbers():
    """A probability or proportion written in words, Chinese tenths or odds never passes, even
    with a supporting source and no digit at all."""
    texts = [
        "Global electric car sales reached 17 million units in 2024, led by China, so a thirty "
        "percent chance is too low.",
        "Thirty per cent of buyers already chose an electric car.",
        "七成概率电动车销量会增长",
        "中国占全球电动车销量的七成以上",
        "三分之一的新车是电动车",
        "Roughly one in three new cars sold was electric.",
        "Nine out of ten analysts expect growth.",
        "The outcome is a coin flip at best.",
        "增长与否是五五开",
        # N in M, hyphenated or spaced, words or digits.
        "Upside deserves more than a one-in-three chance.",
        "Only a 1-in-4 buyer charges at home.",
        "Growth is a one in a hundred shot.",
        "One in every three buyers chose an electric car.",
        # N to M odds.
        "Analysts give growth three-to-one odds.",
        "Growth is a 3-1 shot.",
        # A fraction word next to a chance word, either order.
        "Upside has roughly a third chance.",
        "Upside has a two-thirds chance.",
        "Upside has a nine-tenths likelihood.",
        "The chance is about a third.",
        "The probability is roughly two-thirds, given demand.",
        # Even-odds idioms.
        "Growth is a toss-up.",
        "Growth is a better-than-even bet.",
        "Growth has an even chance.",
        "Growth is more likely than not.",
        "The odds favour growth.",
        "Growth is the odds-on outcome.",
        # Chinese idioms and a half next to a probability word.
        "销量增长十有八九",
        "销量增长八九不离十",
        "增长概率不足一半",
        "增长的可能性超过一半",
        # Round-3 review probes: count nouns in N in M, digit fractions, "probable / likelier
        # than not", odds against, 胜率 next to a half, N-M开 splits.
        "Upside has one chance in three.",
        "Upside has two chances in five.",
        "Upside has one chance out of three.",
        "Nine times out of ten demand recovers.",
        "Demand recovers one time in four.",
        "Growth is more probable than not.",
        "Growth is likelier than not.",
        "Growth is two-to-one against.",
        "Upside has a 1/3 chance.",
        "Only 1/3 of buyers charge at home.",
        "增长的胜率不到一半",
        "增长是三七开的可能",
        "增长与否是四六开",
        "每三辆新车中就有一辆是电动车",
        "十次有九次会增长",
        # The rule: a chance word and any quantity in one sentence (digits that are not a
        # date, number words, fractions, counts, Chinese ratios and multiples).
        "Growth is three times as likely.",
        "The probability, about a third, is too low.",
        "Analysts put the likelihood of growth at 0.4.",
        "Growth has zero chance.",
        "Growth is a 1999 in 2000 chance.",
        "The odds are 2000 to 1.",
        "胜算只有三比一",
        "增长的概率为零",
        "增长的可能性提高了一倍",
        # Odds values in words.
        "The odds are long.",
        "The chances are even.",
        "The odds are stacked against growth.",
    ]
    known = set().union(*(fc.discriminative_numbers(t, NUMBERS) for t in texts))
    kept, dropped = _claims([{"text": t, "sources": ["S1"]} for t in texts], numbers=known)
    assert kept == [] and dropped == Counter({"unverified_number": len(texts)})
    for text in texts:                         # the proportion wall, not the number wall
        assert fc._states_proportion(text), text
    # Ordinary words that contain 成 or "in", ranges, ordinals, magnitudes, dates and
    # direction-only chance words are not proportions or odds.
    allowed = [
        "电池成本持续下降，成员国政策一成不变",
        "One in the region expanded capacity in 2024",
        "The new data are at odds with the earlier survey",
        "Capacity doubled from two to four plants in 2024",
        "Chances of a third term are fading",
        "Approval chances improved in the second half of 2024",
        "A third-party audit confirmed the record sales",
        "电池价格可能下降一半",
        "2024年完成了一成年人调查",
        "全省统一成形工艺",
        "单一成像技术已经成熟",
        "四成都市场",
        # Round-3 review probes: direction-only odds, a rate over a span of time, a year
        # followed by a city.
        "The odds of a recession are rising",
        "The chances are slim that prices fall",
        "Sales rose by 25 in 12 months",
        "2025成都车展",
        "The odds against growth are rising",
        "The odds on a recession are lengthening",
        "Chances of a recession in 2026 are rising",
        "The odds of a Q3 rate cut are rising",
        "The chances are even lower now",
        "The new data are at odds with the 2023 survey of 1,200 buyers",
        "Sales shot up to 17 million units in 2024",
        "One of the likely drivers is cheaper batteries",
        "Sales of zero-emission vehicles are likely to rise",
        "Sales reached 17 million units in 2024. Further growth is likely",
        "Sales rose from 12 to 15 against forecasts",
        "Charging is available 24/7 at most stations",
        "每100公里有15个充电桩",
        "这是导致需求进一步回落的可能性之一",
        "2026年3月1日起补贴退坡，提高了需求回落的可能性",
    ]
    for text in allowed:                       # one call each: a side keeps at most three claims
        kept, dropped = _claims([{"text": text, "sources": ["S1"]}],
                                numbers=fc.discriminative_numbers(text, NUMBERS))
        assert [c["text"] for c in kept] == [text] and not dropped, text
    # Tenths proportions next to those word tails still count.
    tenths = ["七成都来自中国", "四成年轻人选择电动车", "占据七成份额", "七成批发商看好",
              "七成对此表示乐观"]
    kept, dropped = _claims([{"text": t, "sources": ["S1"]} for t in tenths])
    assert kept == [] and dropped == Counter({"unverified_number": len(tenths)})


@pytest.mark.parametrize("probability", [
    "a one-in-three chance", "one chance in three", "nine times out of ten",
    "more probable than not", "likelier than not", "two-to-one against", "a 1/3 chance"])
def test_worded_odds_never_reach_part2_with_the_report_support_check(probability):
    """The review probes: a supported evidence sentence with a worded probability appended is
    rejected, so it can never become the strongest Part-2 claim."""
    support = ReportAgent._semantic_citation_support
    evidence = "Global electric car sales reached 17 million units in 2024, led by China"
    claim = f"{evidence}, so {probability} is too low."
    kept, _ = _claims([{"text": evidence + ".", "sources": ["S1"]}], tags=REAL_TAGS,
                      support=support)
    assert [c["verdict"] for c in kept] == ["valid"]       # the evidence alone is supported
    kept, dropped = _claims([{"text": claim, "sources": ["S1"]}], tags=REAL_TAGS,
                            support=support)
    assert kept == [] and dropped == Counter({"unverified_number": 1})
    result = {"status": "complete", "targets": [{"target_id": "T1", "scenario": "Upside path",
                                                 "claims": {"higher": kept, "lower": []}}]}
    assert fc.render_counter_case_block(result, "English") == ""


def test_worded_odds_are_rejected_when_support_is_undecidable():
    """The review probe: an English claim citing a Chinese source is undecidable (kept as
    unverifiable when clean), so the wall alone keeps its digit-fraction probability out."""
    support = ReportAgent._semantic_citation_support
    tags = {"S1": {"title": "全球电动车展望", "url": "https://iea.example/ev-zh",
                   "supports": ["2024年全球电动车销量达到1700万辆，中国领跑。"]}}
    clean = "Global electric car sales reached 17 million units in 2024, led by China."
    claim = clean[:-1] + ", so a 1/3 chance is too low."
    assert support(claim, tags["S1"]) is None
    kept, dropped = _claims([{"text": clean, "sources": ["S1"]}], tags=tags, support=support)
    assert [c["verdict"] for c in kept] == ["unverifiable"] and not dropped
    kept, dropped = _claims([{"text": claim, "sources": ["S1"]}], tags=tags, support=support)
    assert kept == [] and dropped == Counter({"unverified_number": 1})


def test_non_canonical_markers_are_checked_or_rejected():
    """Marker lists are read marker by marker; a marker form the index cannot resolve is
    never kept in published claim or trigger text."""
    kept, dropped = _claims([
        {"text": "Sales hit a record high [S1, S99]."},                     # list: S99 unknown
        {"text": "Sales hit a record high [S99-a].", "sources": ["S1"]},    # stray form
        {"text": "Sales hit a record high (S99).", "sources": ["S1"]},      # parenthesised
        {"text": "Sales hit a record high （见S4）。", "sources": ["S1"]},    # full-width, prefixed
        {"text": "Sales hit a record high (Source: S1).", "sources": ["S1"]},  # prefixed
        {"text": "Sales hit a record high.", "sources": ["S1, S99"]},       # malformed entry
        {"text": "Sales hit a record high [S1, S4]."},                      # list: both indexed
        {"text": "Sales hit a record high 【S1；S5】。"},                     # full-width list
    ])
    assert dropped == Counter({"unknown_source": 6})
    assert [(c["text"], c["sources"]) for c in kept] == [
        ("Sales hit a record high .", ["S1", "S4"]), ("Sales hit a record high 。", ["S1", "S5"])]
    # A product name that merely looks like a marker inside parentheses is ordinary text.
    galaxy = "Sales of the Galaxy (Samsung S24) hit a record high."
    kept, dropped = _claims([{"text": galaxy, "sources": ["S1"]}], numbers=("17", "24"))
    assert [c["text"] for c in kept] == [galaxy] and not dropped
    kept = fc.validate_triggers([
        _trigger(signal="Global electric car sales [S1, S99]"),           # S99 dropped, S1 kept
        _trigger(signal="Global electric car sales (S1)"),                # stray in signal
        _trigger(threshold_or_event="above 25 million [S2-b]"),           # stray in threshold
        _trigger(signal="Global electric car sales [S2, S3]", sources=[]),
    ], REAL_TAGS)
    assert [(t["signal"], t["threshold_or_event"], t["sources"]) for t in kept] == [
        ("Global electric car sales", "above 25 million", ["S1"]),
        ("Global electric car sales", "above 25 million", ["S2", "S3"])]


def test_valid_claims_never_carry_a_rejected_source():
    claims = [
        {"text": "Supported by one, contradicted by another", "sources": ["S1", "S2"]},
        {"text": "Contradicted first, supported later", "sources": ["S2", "S5", "S2"]},
        {"text": "Undecided plus contradicted", "sources": ["S3", "S2"]},
        # More than four candidates: supporting sources are kept before undecided ones.
        {"text": "Many sources", "sources": ["S3", "S6", "S7", "S8", "S1"]},
    ]
    kept, dropped = _claims(claims[:3])
    kept_more, _ = _claims(claims[3:])
    for claim in kept + kept_more:
        assert all(STUB_TAGS[tag]["verdict"] is not False for tag in claim["sources"])
    assert [(c["verdict"], c["sources"]) for c in kept] == [
        ("valid", ["S1"]), ("valid", ["S5"]), ("unverifiable", ["S3"])]
    assert dropped == Counter({fc.TAG_DROP_KEY: 3})
    assert [(c["verdict"], c["sources"]) for c in kept_more] == [("valid", ["S3", "S6", "S7", "S1"])]


def test_claim_caps():
    long_text = "Sales keep growing across every major market " * 20
    kept, dropped = _claims([
        {"text": long_text, "sources": ["S1", "S2", "S3", "S4", "S5"]},
        {"text": "Second valid claim", "sources": ["[S4]"]},
        {"text": "Third valid claim", "sources": [5]},
        {"text": "Fourth valid claim", "sources": ["S1"]},
        {"text": "Fifth valid claim", "sources": ["S1"]},
    ])
    assert len(kept) == 3 and dropped == Counter({"over_cap": 2, fc.TAG_DROP_KEY: 1})
    assert len(kept[0]["text"]) <= fc.MAX_CLAIM_CHARS and kept[0]["text"].endswith("…")
    assert kept[0]["sources"] == ["S1", "S3", "S4", "S5"]          # S2 rejected; at most four
    assert [c["sources"] for c in kept[1:]] == [["S4"], ["S5"]]    # markers normalised
    # Malformed and empty items are counted, never kept.
    kept, dropped = _claims([42, {"text": "  "}, None])
    assert kept == [] and dropped == Counter({"malformed": 2, "empty": 1})


def test_cuts_never_publish_a_different_number():
    """The review probe: a number straddling the 400-character cut never becomes another
    number ('175 million' is not published as '17'); a number left at the end of a cut, which
    may have lost its scale ('175' of '175 million', '1.75' of '1.75亿'), is dropped too."""
    lead = ("Global electric car sales reached 17 million units in 2024, led by China."
            + " Charging networks keep expanding across every major market." * 5)
    straddling = lead + " the total fleet reaches 175 million cumulative units."
    at_the_cut = lead + " the fleet stands near 175 million cumulative units."
    assert straddling.index("175") == fc.MAX_CLAIM_CHARS - 2       # the cut falls inside it
    assert at_the_cut.index("175") + 3 == fc.MAX_CLAIM_CHARS - 1   # it ends right at the cut
    kept, dropped = _claims([{"text": straddling, "sources": ["S1"]},
                             {"text": at_the_cut, "sources": ["S1"]}], numbers=("17", "175"))
    assert not dropped
    assert kept[0]["text"].endswith("the total fleet reaches…")
    assert kept[1]["text"].endswith("the fleet stands near…")
    for claim in kept:
        assert len(claim["text"]) <= fc.MAX_CLAIM_CHARS
        assert fc.discriminative_numbers(claim["text"], NUMBERS) == {"17"}
    # Chinese: a scale attached to the number, and a decimal straddling the cut.
    scale = "累计" * 195 + "预计将达到1.75亿辆。"
    decimal = "累计" * 197 + "已达到1.75亿辆。"
    assert scale.index("亿") == decimal.index(".") + 1 == fc.MAX_CLAIM_CHARS - 1
    assert fc._cap(scale, fc.MAX_CLAIM_CHARS).endswith("预计将达到…")
    assert fc._cap(decimal, fc.MAX_CLAIM_CHARS).endswith("已达到…")
    # Trigger fields (300 characters): a threshold whose number straddles the cut keeps no
    # partial number, so without a date it no longer has a numeric threshold.
    threshold = "sales climb " * 24 + "far above 25 million units"
    assert threshold.index("25") == fc.MAX_TRIGGER_FIELD_CHARS - 2
    assert fc.validate_triggers([_trigger(threshold_or_event=threshold)], REAL_TAGS) == []
    [kept_trigger] = fc.validate_triggers([_trigger(threshold_or_event=threshold,
                                                    by="2027-06-30")], REAL_TAGS)
    assert kept_trigger["threshold_or_event"].endswith("far above…")
    # Words are never split either, and nothing whole left means nothing published.
    text = "Sales keep growing across every major market " * 20
    words = fc._cap(text, fc.MAX_CLAIM_CHARS)
    assert words.endswith("every major…") and text.startswith(words[:-1])
    assert fc._cap("x" * 500, fc.MAX_CLAIM_CHARS) == ""


def test_claim_walls_with_the_report_support_check():
    support = ReportAgent._semantic_citation_support
    kept, dropped = _claims([
        {"text": "Global electric car sales reached 17 million units in 2024, led by China.",
         "sources": ["S1"]},
        {"text": "Interconnection queues across regional grids keep the rollout slow.",
         "sources": ["S1"]},
        {"text": "Global electric car sales reached 17 million units in 2024, led by China, so a "
                 "thirty percent chance is too low.", "sources": ["S1"]},
        {"text": "Global electric car sales reached 17 million units in 2024, led by China.",
         "sources": ["S1", "S2"]},
    ], tags=REAL_TAGS, support=support)
    assert [(c["id"], c["verdict"], c["sources"]) for c in kept] == [
        ("T1.H1", "valid", ["S1"]), ("T1.H2", "valid", ["S1"])]
    assert dropped == Counter({"source_mismatch": 1, "unverified_number": 1, fc.TAG_DROP_KEY: 1})


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
         {"signal": "Global electric car sales", "direction": "raises",
          "threshold_or_event": "above 25 million",
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


def test_packet_numbers_leave_out_market_anchors_and_urls():
    """Only the evidence sections feed the known-number set: a market-implied figure or a URL
    digit run never lets a claim number through, while the same figure in evidence does."""
    packet = _packet(
        sources_index="[S1] Global EV Outlook — https://iea.example/reports/884412\n"
                      "[S2] Battery price survey ｜supports: pack prices fell to 115 dollars",
        market_pack="Polymarket: EV sales above 20 million — implied 0.42 (volume 31000)")
    assert "0.42" in packet["text"] and "884412" in packet["text"]
    numbers = packet["numbers"]
    assert {"17", "115"} <= numbers
    assert not numbers & {"0.42", "31000", "884412"}
    kept, dropped = _claims([
        {"text": "Traders put it at 0.42, so the case is weak", "sources": ["S1"]},
        {"text": "Report 884412 shows growth", "sources": ["S1"]},
        {"text": "Pack prices fell to 115 dollars", "sources": ["S1"]},
    ], numbers=numbers)
    assert [c["text"] for c in kept] == ["Pack prices fell to 115 dollars"]
    assert dropped == Counter({"unverified_number": 2})
    # The contested table is evidence: its numbers count.
    contested = _packet(contested_block="- Claim A: 31000 chargers [S2]")
    assert "31000" in contested["numbers"]


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
    row = {"signal": "Global electric car sales", "direction": "raises",
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
        {"signal": "Global electric car sales", "direction": "raises",
         "threshold_or_event": "a policy shift", "by": "2027-06-30", "sources": ["S1"]},
        {"signal": "Global electric car sales", "direction": "raises",
         "threshold_or_event": "above 25 million", "by": "", "sources": ["S2"]},
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
    assert rows[0] == {"indicator": "Global electric car sales", "date_or_trigger": "above 25 million",
                       "by": "", "discriminates": "Path A", "source": "counter_case",
                       "sources": ["S1"], "direction": "raises",
                       "threshold_or_event": "above 25 million"}


def test_trigger_support_wall():
    """Triggers pass the claim wall: a marker the support check rejects (for the signal, or
    for the claim the publish-time citation check reads in the How-to-Verify row) is removed,
    and a trigger left without a marker is dropped."""
    support = ReportAgent._semantic_citation_support
    stats = Counter()
    kept = fc.validate_triggers([
        _trigger(signal="Annual electric car sales"),                    # S1 rejects it -> dropped
        _trigger(sources=["S2", "S1"]),                                   # S2 rejects -> ["S1"]
        _trigger(signal="全球电动车年销量"),                                  # cross-language: None
    ], REAL_TAGS, support_fn=support, stats=stats)
    assert [(t["signal"], t["sources"]) for t in kept] == [
        ("Global electric car sales", ["S1"]), ("全球电动车年销量", ["S1"])]
    assert stats == Counter({fc.TAG_DROP_KEY: 2})

    # The published-row claim is checked too, with the row the trigger publishes as.
    seen = []

    def _published(row):
        seen.append(row)
        return "Interconnection queues lengthened across most regional grids."

    kept = fc.validate_triggers([_trigger(by="2027-12-31")], REAL_TAGS, scenario="Upside path",
                                support_fn=support, published_claim_fn=_published)
    assert kept == []
    assert seen == [{"indicator": "Global electric car sales", "date_or_trigger": "2027-12-31",
                     "by": "2027-12-31", "discriminates": "Upside path", "source": "counter_case",
                     "sources": ["S1"], "direction": "raises",
                     "threshold_or_event": "above 25 million"}]
    # A published claim the check cannot decide keeps the marker; a failing claim builder
    # falls back to the signal check alone.
    assert fc.validate_triggers([_trigger()], REAL_TAGS, support_fn=support,
                                published_claim_fn=lambda row: "全球电动车")[0]["sources"] == ["S1"]

    def _broken(row):
        raise RuntimeError("no table")

    assert fc.validate_triggers([_trigger()], REAL_TAGS, support_fn=support,
                                published_claim_fn=_broken)[0]["sources"] == ["S1"]


def test_triggers_dated_before_as_of_lose_the_date():
    triggers = [
        _trigger(by="2026-08-31"),                                        # past -> '' (threshold)
        _trigger(by="2026-09-01"),                                        # the as-of day is kept
        _trigger(by="2025-01-01", threshold_or_event="a policy shift"),   # past, no digit -> dropped
        _trigger(by="2027-06-30", threshold_or_event="a policy shift"),   # future date -> kept
    ]
    for as_of in ("2026-09-01", date(2026, 9, 1), datetime(2026, 9, 1, 12, 0)):
        kept = fc.validate_triggers(triggers, REAL_TAGS, as_of=as_of)
        assert [(t["by"], t["threshold_or_event"]) for t in kept] == [
            ("", "above 25 million"), ("2026-09-01", "above 25 million"),
            ("2027-06-30", "a policy shift")]
    # Without an as-of every real date stands.
    assert [t["by"] for t in fc.validate_triggers(triggers, REAL_TAGS)] == [
        "2026-08-31", "2026-09-01", "2025-01-01"]


def test_triggers_that_state_a_probability_are_dropped():
    """A trigger is published as one row, so its signal and threshold are read together: a
    chance word and a quantity there state a probability and drop the trigger. A chance word
    without a quantity is direction only."""
    kept = fc.validate_triggers([
        _trigger(signal="Fed rate-cut probability", threshold_or_event="above 50%"),
        _trigger(signal="Rate-cut odds", threshold_or_event="above 1 in 3"),
        _trigger(threshold_or_event="one chance in three of topping 25 million"),
        _trigger(signal="Market-implied probability of a 2027 recession",
                 threshold_or_event="above 0.4"),
        _trigger(signal="全球电动车销量增长的概率", threshold_or_event="超过2500万辆"),
        _trigger(),
        _trigger(signal="Odds of a rate cut", threshold_or_event="a policy shift",
                 by="2027-06-30"),
    ], REAL_TAGS)
    assert [(t["signal"], t["threshold_or_event"]) for t in kept] == [
        ("Global electric car sales", "above 25 million"),
        ("Odds of a rate cut", "a policy shift")]


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
    assert result["tags_removed"] == {"claims": 0, "triggers": 0}
    summary = fc.forecast_summary(result, "abc")
    assert summary == {"schema": "drf.counter_case/v1", "status": "complete",
                       "artifact": "counter_case.json", "artifact_sha256": "abc",
                       "claims_valid": 3, "claims_unverifiable": 0, "claims_dropped": 0,
                       "triggers": 1, "triggers_published": 1}
    text = fc.artifact_text(result)
    assert json.loads(text) == result and text == json.dumps(result, ensure_ascii=False,
                                                             sort_keys=True, indent=2)


def test_render_block_logs_targets_left_out(caplog):
    result, _, _ = _run()
    full = fc.render_counter_case_block(result, "English")
    first = full.split('\n- T2 ')[0]
    with caplog.at_level("WARNING", logger=fc.__name__):
        cut = fc.render_counter_case_block(result, "English", max_chars=len(first))
    assert cut == first
    assert any("T2" in r.getMessage() and "counter_case.json" in r.getMessage()
               for r in caplog.records)
    caplog.clear()
    with caplog.at_level("WARNING", logger=fc.__name__):
        assert fc.render_counter_case_block(result, "English") == full
    assert not caplog.records


def test_how_to_verify_rows():
    """Counter-case rows: signal, its [S#] and a separate counter-case label (so a stripped
    marker leaves no orphan), date plus threshold plus direction; they never compete with the
    first 20 research rows for table space."""
    from app.services.forecast_extractor import render_resolution_block, resolution_indicator_table
    research = [{"indicator": f"Research indicator {n}", "date_or_trigger": f"2027-01-{n:02d}",
                 "discriminates": "Upside path"} for n in range(1, 26)]
    counter = [
        {"indicator": "Global electric car sales", "date_or_trigger": "2027-12-31", "by": "2027-12-31",
         "discriminates": "Upside path", "source": "counter_case", "sources": ["S1", "S3"],
         "direction": "raises", "threshold_or_event": "above 25 million units"},
        {"indicator": "Battery pack prices", "date_or_trigger": "back above 140 dollars", "by": "",
         "discriminates": "Downside path", "source": "counter_case", "sources": ["S2"],
         "direction": "lowers", "threshold_or_event": "back above 140 dollars"},
    ]
    en = resolution_indicator_table(research + counter, "English")
    assert en[:2] == ["| Indicator | Due / trigger | Discriminates scenario |", "|---|---|---|"]
    assert len(en) == 2 + 20 + 2
    assert en[2] == "| Research indicator 1 | 2027-01-01 | Upside path |"
    assert en[21] == "| Research indicator 20 | 2027-01-20 | Upside path |"
    assert en[22:] == [
        "| Global electric car sales [S1][S3] (counter-case review) | 2027-12-31: above 25 million "
        "units (raises) | Upside path |",
        "| Battery pack prices [S2] (counter-case review) | back above 140 dollars (lowers) | "
        "Downside path |"]
    zh = resolution_indicator_table(counter, "Chinese")
    assert zh == ["| 指标 | 到期/触发 | 关联情景 |", "|---|---|---|",
                  "| Global electric car sales[S1][S3]（反证审查） | 2027-12-31：above 25 million units"
                  "（上调） | Upside path |",
                  "| Battery pack prices[S2]（反证审查） | back above 140 dollars（下调） | Downside path |"]
    # Research rows alone: exactly the first 20, as before.
    assert resolution_indicator_table(research, "English") == en[:22]
    assert resolution_indicator_table([], "English") == [] and resolution_indicator_table(None) == []
    block = render_resolution_block({"scenarios": [{"name": "Upside path", "probability": 0.5}]},
                                    research + counter, language="English")
    assert block.endswith("\n".join(["### Indicators to Watch (check at expiry/trigger)", *en]))


def test_merge_indicators_dedupes_by_casefolded_text():
    research = [{"indicator": "Annual EV Sales", "date_or_trigger": "2026-Q4"}]
    counter = [{"indicator": "annual ev sales ", "source": "counter_case"},
               {"indicator": "Pack prices", "source": "counter_case"},
               {"indicator": "PACK PRICES", "source": "counter_case"}]
    merged = fc.merge_indicators(research, counter)
    assert merged == research + [{"indicator": "Pack prices", "source": "counter_case"}]
    assert fc.merge_indicators(research, []) == research


def test_triggers_on_one_signal_for_different_scenarios_all_publish(caplog):
    """Counter-case rows are deduped against research indicators by indicator text, but among
    themselves only exact repeats go; every left-out row is logged, and forecast.counter_case
    counts the rows that actually publish."""
    upside = {"signal": "Global electric car sales", "direction": "raises",
              "threshold_or_event": "above 25 million", "by": "2027-12-31", "sources": ["S1"]}
    downside = {"signal": "Global electric car sales", "direction": "lowers",
                "threshold_or_event": "below 15 million", "by": "", "sources": ["S1"]}
    result = {"schema": fc.SCHEMA, "status": "complete", "dropped": {}, "targets": [
        {"target_id": "T1", "scenario": "Upside path", "claims": {}, "triggers": [upside, dict(upside)]},
        {"target_id": "T2", "scenario": "Downside path", "claims": {}, "triggers": [downside]}]}
    rows = fc.triggers_to_indicators(result)
    with caplog.at_level("INFO", logger=fc.__name__):
        merged = fc.merge_indicators([], rows)
    assert [(r["discriminates"], r["direction"], r["threshold_or_event"]) for r in merged] == [
        ("Upside path", "raises", "above 25 million"), ("Downside path", "lowers", "below 15 million")]
    assert [r.getMessage() for r in caplog.records] == [
        "counter-case: trigger 'global electric car sales' not published as an indicator "
        "(trigger_duplicate)"]
    summary = fc.forecast_summary(result, "abc")
    assert (summary["triggers"], summary["triggers_published"]) == (3, 2)

    research = [{"indicator": "Global Electric Car Sales", "date_or_trigger": "2027-06-30"}]
    caplog.clear()
    with caplog.at_level("INFO", logger=fc.__name__):
        assert fc.merge_indicators(research, rows) == research
    assert len(caplog.records) == 3
    assert all(r.getMessage().endswith("(research_duplicate)") for r in caplog.records)
    summary = fc.forecast_summary(result, "abc", research_indicators=research)
    assert (summary["triggers"], summary["triggers_published"]) == (3, 0)


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
