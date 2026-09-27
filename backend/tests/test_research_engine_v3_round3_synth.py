"""Review round 3 regressions of the deep-research engine v3: synthesis, QA and
the report text helpers (cluster "engine synthesis").

C13 deterministic sections never share a finding and a section emptied by
cross-section deduplication is rebuilt from unused findings or omitted: a bare
heading is never published; C14 scenario weights restated in prose are made
equal to the frame when the restatement is unambiguous and flagged by QA
otherwise; C23 a writer's own probability-bearing scenario loses its
probability; C15 the scenario section is the one the planner designates or the
best-scoring title, never a use-case title that merely contains "scenario" or
"场景"; C17 a drifted heading in a multi-section writer reply maps to its
section and a section is never published twice; C18 citation groups with a
locator, label or "Source" prefix are canonical, parenthesised product,
standard and term names are not citations, parsing never raises and QA sweeps
unresolved citation syntax; C19/C22 deterministic summaries and trimmed replies
end at complete sentences ("U.S.", "e.g.", numbers and markers are never
split) and a cut list keeps its complete bullets; C21 number verification
treats scale and digit-grouping variants as the same value; C27 QA rewrites run
as one fan-out after a prime of the shared writer prefix.

Offline and deterministic: the fakes and ``run_engine`` harness of
``test_research_engine_v3`` (scripted model, injected search/fetch, the real
bridge module with prediction markets and charts stubbed), no network, no LLM,
no sleeps.  The one wall-clock guard (C18) uses a bound far above the linear
cost and far below the old exponential/cubic one.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import types

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg
forecast_inputs_from_report_markdown = v3.forecast_inputs_from_report_markdown

ZH_QUESTION = "2027年底前全球数据中心装机容量会超过250吉瓦吗？"
FRAME_EN = [lr.Scenario("Base case", 50, "t"), lr.Scenario("Accelerated build-out", 30, "t"),
            lr.Scenario("Stalled expansion", 20, "t")]
FRAME_ZH = [lr.Scenario("基准情景", 50, "t"), lr.Scenario("加速扩张", 30, "t"), lr.Scenario("扩张停滞", 20, "t")]


def _report(out) -> str:
    return (out / "research_report.md").read_text(encoding="utf-8")


def _qa(out) -> dict:
    return json.loads((out / "v3" / "qa.json").read_text(encoding="utf-8"))


def _body_sections(report: str) -> list[tuple[str, str]]:
    return [(title, body) for title, body in lr.report_sections(report) if title != "References"]


def _paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body)
            if len(p.strip()) >= 80 and not p.strip().startswith(("#", "|"))]


# =============================================================== C18 citation groups

@pytest.mark.parametrize("raw, expected", [
    ("demand grew 12% [S30, p. 4].", "demand grew 12% [S30]."),
    ("demand grew 12% [S30; IEA 2025].", "demand grew 12% [S30]."),
    ("demand grew 12% [S30: IEA survey].", "demand grew 12% [S30]."),
    ("according to the [Source 30] survey", "according to the [S30] survey"),
    ("容量增长【S3，第4页】。", "容量增长[S3]。"),
    ("rose [S12, 2026-02-03].", "rose [S12]."),
    ("rose [S30, Fig. 2(a)].", "rose [S30]."),
    ("x (Source: S30) y", "x [S30] y"),
])
def test_r3_citation_groups_drop_their_locator_or_label(raw, expected):
    assert lr.normalize_citations(raw) == expected


@pytest.mark.parametrize("text", [
    "Samsung's flagship (S24) sold 30 million units",
    "The ISSB standards (S1 and S2) take effect in 2026",
    "ISSB standards (S1, S2) take effect in 2026",
    "In the first half (S1 2025) revenue rose 8%",
    "市场份额（S1，2026-02-03）上升",
    "result (S1 2026-04-06) stands",
    "tier (S1, fetched) (VERIFIED)",
    "the (Source 30) figure",
    "a (S3 & S5) pair",
    "see [page-S30] for the table",
])
def test_r3_parenthesised_names_and_dates_are_not_citations(text):
    assert lr.normalize_citations(text) == text


def test_r3_real_round_bracket_citations_still_count():
    assert lr.normalize_citations("capacity rose (S3) in 2023") == "capacity rose [S3] in 2023"
    assert lr.normalize_citations("a （S12，S13）。") == "a [S12][S13]。"
    assert lr.normalize_citations("x [S3-5] and [S3-S5-S7]") == "x [S3][S4][S5] and [S3][S4][S5][S7]"


@pytest.mark.parametrize("text", [
    "[S12, 2026-02-03]", "（S1，2026-02-03）", "(S1 2026-04-06)", "[S3-S5-S7]", "[S3-5-7]",
    "[S" + "9" * 5000 + "]", "[S1-" + "9" * 5000 + "]",
])
def test_r3_citation_parsing_never_raises(text):
    """Dates inside a group and double ranges made the group parser index a
    dash as a number (ValueError), which crashed agent notes and QA alike."""
    lr.normalize_citations(text)
    rows = {12: {"sid": 12, "fetched": True}, 1: {"sid": 1, "fetched": True}, 3: {"sid": 3}}.get
    notes = f"## Findings\n- Capacity reached 176 GW in 2023 {text} [S12] (REPORTED)\n## Conflicts"
    _, parts = lr.postprocess_notes("K1", notes, rows, lambda sid: frozenset({"176", "2023"}))
    assert parts["facts"] and 12 in parts["facts"][0]["sids"]


def test_r3_citation_normaliser_is_linear_on_digit_and_space_runs():
    """The old group pattern took ~4 s on '[S' + 25 digits (exponential) and
    ~5 s on '[S1' + 1,500 spaces (cubic); both are linear now."""
    for text in ("[S" + "1" * 25, "[S1" + " " * 1500 + "x", "[S1, " + " " * 20_000 + "x",
                 "[Source " + "1" * 50_000):
        started = time.perf_counter()
        lr.normalize_citations(text)
        lr.strip_stale_citations(text)
        lr.stale_citation_tokens(text)
        assert time.perf_counter() - started < 1.0


def test_r3_unresolved_citation_groups_are_removed_and_prose_pointers_flagged():
    text = "a [S1 and S2] b [S3] c [Source 30 and 31] d [page-S3] e."
    cleaned, removed = lr.strip_stale_citations(text)
    assert cleaned == "a b [S3] c d [page-S3] e." and removed == ["[S1 and S2]", "[Source 30 and 31]"]
    assert lr.stale_citation_tokens("as reported by S30; Galaxy S24 sold; IFRS S1; [S2]; Source 30; 来源S4") == [
        "reported by S30", "Source 30", "来源S4"]


class LocatorCitingWorld(v3.World):
    """The writer of the first section cites with a page locator and with an
    "and" group that no normaliser rule can resolve."""

    def writer(self, call):
        reply = super().writer(call)
        context = call["messages"][2][1]
        sids = re.findall(r"^\[S(\d+)\]", context.split("SOURCE INDEX", 1)[-1], re.M)
        if "## Market Baseline" not in reply.content or len(sids) < 2:
            return reply
        extra = (f"\n\nOperators reported 1,234 million dollars of capital expenditure [S{sids[-1]}, p. 4]. "
                 f"Queues exceed 40 months [S{sids[0]} and S{sids[1]}].")
        text = reply.content.replace("## Market Baseline\n\n", "## Market Baseline\n\n" + extra.strip() + "\n\n", 1)
        return v3.ai(text, out=1500)


def test_r3_locator_citations_reach_the_references_and_stale_groups_never_ship(tmp_path, bridge):
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, LocatorCitingWorld())
    assert rc == 0, meta.get("error")
    report, qa = _report(out), _qa(out)
    body = lr.strip_references(report)
    assert ", p. 4]" not in body and not re.search(r"\[S\d+ and S\d+\]", body)
    marker = re.search(r"capital expenditure (\[S\d+\])", body)
    assert marker, "the locator citation was not normalised"
    number = int(marker.group(1)[2:-1])
    refs = report.split("\n## References\n", 1)[1]
    assert re.search(rf"^- \[S{number}\] ", refs, re.M)
    assert lr.stale_citation_tokens(body) == []
    check = next(c for c in qa["checks"] if c["name"] == "no_stale_citations")
    assert check["passed"] is True
    removed = [r for r in qa["repaired"] if r["check"] == "no_stale_citations"]
    assert removed and all(" and S" in group for group in removed[0]["groups"])


# =============================================================== C21 number verification

def _verify(page: str, fact: str) -> dict:
    notes = f"## Findings\n- {fact} [S1] (VERIFIED)\n## Conflicts"
    _, parts = lr.postprocess_notes("K1", notes, {1: {"sid": 1, "fetched": True}}.get,
                                    lambda sid: lr.page_number_set(page))
    return parts["facts"][0]


@pytest.mark.parametrize("page, fact", [
    ("Global spending reached $1,200 billion in 2024.", "Global spending reached $1.2 trillion in 2024"),
    ("Global spending reached $1.2 trillion in 2024.", "Global spending reached $1,200 billion in 2024"),
    ("Global spending reached $1.2tn in 2024.", "Global spending reached $1,200bn in 2024"),
    ("Global spending reached $1.2 trillion in 2024.", "Global spending reached $1,200,000,000,000 in 2024"),
    ("Capacity reached 12 500 MW at end-2024.", "Capacity reached 12,500 MW at end-2024"),
    ("Capacity reached 12 500 MW at end-2024.", "Capacity reached 12,500 MW at end-2024"),
    ("Capacity reached 12 500 MW at end-2024.", "Capacity reached 12,500 MW at end-2024"),
    ("Capacity reached 12 500 MW at end-2024.", "Capacity reached 12,500 MW at end-2024"),
    ("Capacity reached 12'500 MW at end-2024.", "Capacity reached 12,500 MW at end-2024"),
    ("Capacity reached 12,500 MW at end-2024.", "Capacity reached 12 500 MW at end-2024"),
    ("2024年全国数据中心投资达1.2万亿元。", "2024年全国数据中心投资达12000亿元"),
    ("2024年全国数据中心投资达12000亿元。", "2024年全国数据中心投资达1.2万亿元"),
    ("营收为３，４５６亿元，同比增长１５．５％。", "营收为3,456亿元，同比增长15.5%"),
    ("The share rose to 15 % in 2024.", "The share rose to 15% in 2024"),
])
def test_r3_number_verification_accepts_scale_and_format_variants(page, fact):
    verified = _verify(page, fact)
    assert verified["tag"] == "VERIFIED", verified.get("missing_numbers")


@pytest.mark.parametrize("page, fact", [
    ("Revenue was $3.4 billion in 2023.", "Revenue was $34 billion in 2023"),
    ("The fund holds 1,234 positions.", "The fund holds 1.234 million positions"),
    ("出口额为6,800亿元。", "Exports reached 6.8 trillion yuan"),        # 6.8e11 on the page, not 6.8e12
    ("Spending reached $1,200 billion in 2024.", "Spending reached $12 trillion in 2024"),
    ("Capacity reached 12 GW at 500 sites.", "Capacity reached 12 500 MW"),
    ("Capacity was 1,234.50 MW in 2023; growth 12%.", "Capacity will be 2,000 MW in 2030"),
    # a fact's own scale word counts: a joined or scaled page value never
    # matches the bare digits of a number at another scale
    ("The agency reported 8 391 094 000 000 in its survey.", "The agency reported 8,391,094,000,000 thousand"),
    ("The agency reported 406708.5万 in its survey.", "The agency reported 4,067,085,000 thousand"),
    ("The agency reported 259 000 in its survey.", "The agency reported 0.0259万"),
    ("The agency reported 1\u00a0435\u00a0436 in its survey.", "The agency reported 1435436 thousand"),
])
def test_r3_number_verification_still_rejects_other_values(page, fact):
    assert _verify(page, fact)["tag"] == "UNVERIFIED"


def test_r3_fact_numbers_map_to_their_full_values():
    assert lr.fact_number_values("$1.2 trillion and 12000亿 and $300m but 5 m of cable") == {
        "1.2": frozenset({"=1200000000000"}), "12000": frozenset({"=1200000000000"}),
        "300": frozenset({"=300000000"}), "5": frozenset({"=5"})}
    page = lr.page_number_set("12 500 MW and 1,200 billion")
    assert {"12", "500", "1200", "=12500", "=1200000000000"} <= page
    assert "12500" not in page and "=12" not in page and "=1200" not in page


# =============================================================== C19/C22 sentence boundaries

@pytest.mark.parametrize("text, expected", [
    ("Capacity reached 176 GW in 2023 [S1]. Demand is projected to grow 12% a year according to the U.S. "
     "Energy Information Administration, while grid queues exceed 40 mon", "Capacity reached 176 GW in 2023 [S1]."),
    ("Growth came e.g. from AI [S1]. Firms such as Apple Inc. expand and", "Growth came e.g. from AI [S1]."),
    ("Demand rose [S1]. Dr. Smith and J. Doe expect i.e. more", "Demand rose [S1]."),
    ("- Capacity reached 176 GW in 2023 [S1]\n- Demand grew 12% in 2024 [S2]\n- Grid queues now exceed 40 mon",
     "- Capacity reached 176 GW in 2023 [S1]\n- Demand grew 12% in 2024 [S2]"),
    ("Intro [S1].\n\nKey signposts:\n- a [S1]\n- b [S2]\n- c cu", "Intro [S1].\n\nKey signposts:\n- a [S1]\n- b [S2]"),
    ("- 装机容量达到176吉瓦[S1]\n- 需求增长12%[S2]\n- 排队时间超过40个",
     "- 装机容量达到176吉瓦[S1]\n- 需求增长12%[S2]"),
    ("1. First signpost [S1]\n2. Second signpost [S2]\n3. Third sig",
     "1. First signpost [S1]\n2. Second signpost [S2]"),
    ("Intro one. Intro two.\n- only item is cu", "Intro one. Intro two."),
    ("Key signposts:\n- cut", ""),
])
def test_r3_trim_cut_reply_respects_abbreviations_and_keeps_complete_bullets(text, expected):
    assert lr.trim_cut_reply(text) == expected


def test_r3_sentence_excerpt_never_splits_a_number_or_a_marker():
    filler = "电网容量资本开支冷却许可涡轮租赁变电站" * 16
    lead = "需求驱动：" + filler[:290] + "2,345.6亿美元[S1]，同比增长18.5%[S1]。后续分析。"
    assert lr.sentence_excerpt(lead, 300).endswith("2,345.6亿美元[S1]，同比增长18.5%[S1]。")
    short = "Capacity reached 176 GW [S1]. " + "More detail follows here. " * 20
    excerpt = lr.sentence_excerpt(short, 300)
    assert len(excerpt) <= 300 and excerpt.endswith(".") and not excerpt.endswith("…")
    no_break = "市场：" + filler * 3 + "达1.8亿[S3]"
    cut = lr.sentence_excerpt(no_break, 300)
    assert cut.endswith("…") and not re.search(r"(?:\[S?\d*|\d[\d,.]*)…$", cut)
    ranged = "占全球" + "的" * 290 + "190–210 GW，" + "的" * 50
    assert not re.search(r"\d[–-]?…$", lr.sentence_excerpt(ranged, 300))
    grouped = "x" * 200 + " value 12 500 000 units " + "y" * 200
    assert lr.sentence_excerpt(grouped, 220).endswith(" value 12 500 000…")
    assert lr.sentence_excerpt(grouped, 216).endswith(" value…")     # never "12 500…"


class ZhLongLeadWorld(v3.World):
    """Chinese sections whose first paragraph runs past 300 characters with a
    figure or a marker right at the old hard cut; the executive-summary reply
    is unusable, so the deterministic summary is published."""

    def paragraph(self, title, seed, cite):
        words = "电网容量资本开支冷却许可涡轮租赁变电站合同融资时延需求供给价格政策"
        digest = hashlib.sha1(f"{title}{seed}".encode()).hexdigest()
        filler = "".join(words[int(c, 16)] for c in digest * 8)
        prefix = f"{title}：{filler}"
        target = 295 if seed % 2 == 0 else 293
        prefix = prefix[:target] if len(prefix) >= target else prefix + "数" * (target - len(prefix))
        if seed % 2 == 0:
            return prefix + f"2,345.6亿美元{cite}，同比增长18.5%{cite}。"
        return prefix + f"达1.8亿{cite}，同比增长18.5%{cite}。"

    def exec_summary(self, call):
        return v3.ai("## 执行摘要\n\n暂无。")


def test_r3_deterministic_chinese_summary_keeps_whole_figures_and_markers(tmp_path, bridge):
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, ZhLongLeadWorld(language="Chinese"),
                                        question=ZH_QUESTION)
    assert rc == 0, meta.get("error")
    assert meta["executive_summary_origin"] == "fallback"
    summary = _report(out).split("## 执行摘要", 1)[1].split("\n## ", 1)[0]
    leads = [line for line in summary.strip().splitlines() if line.startswith("- ")]
    assert leads
    for line in leads:
        assert not re.search(r"(?:\[S?\d*|\d[\d,.]*)…$", line), line
        assert line.endswith("。"), line


# =============================================================== C13 deterministic sections

def _facts(kid: str, n: int, base: int) -> dict:
    return {"id": kid, "facts": [{"text": f"{kid} finding {i} on capacity [S{base + i}]", "sids": [base + i],
                                  "tag": "VERIFIED" if i % 2 == 0 else "REPORTED"} for i in range(n)]}


def test_r3_deterministic_sections_never_share_a_finding():
    records = {"K1": _facts("K1", 6, 1), "K2": _facts("K2", 3, 20)}
    sections = [lr.OutlineSection(1, "Market Baseline", ["K1"], "capacity"),
                lr.OutlineSection(2, "Scenarios and Probabilities", ["K1", "K2"], "paths", True),
                lr.OutlineSection(3, "Key Drivers", [], ""),
                lr.OutlineSection(4, "Signposts to Watch", [], "")]
    bodies = lr.fallback_section_bodies(sections, records, "English")
    lines = [line for body in bodies.values() for line in body.splitlines() if line.startswith("- ")]
    facts = [line for line in lines if "finding" in line]
    assert len(facts) == len(set(facts)) == 9           # every finding published, none twice
    assert all("finding" in bodies[index] for index in (1, 2, 3, 4))
    assert set(bodies[1].splitlines()) <= {f"- {f['text']}" for f in records["K1"]["facts"]}
    again = lr.fallback_section_bodies(sections, records, "English")
    assert again == bodies                              # deterministic
    only = lr.fallback_section_bodies(sections, {"K1": _facts("K1", 1, 1)}, "English")
    assert sum("finding" in body for body in only.values()) == 1
    assert only[4] == f"- {lr._text('English', 'no_evidence')}"
    assert lr.fallback_section_bodies(sections[:1], {}, "English", empty_when_none=True) == {1: ""}


def _filtered(call, role):
    if role == "SECTION WRITING TASK":
        return RuntimeError("Error code: 400 - {'error': {'code': '1301', 'message': "
                            "'系统检测到输入或生成内容可能包含不安全或敏感内容'}}")
    return None


def _assert_no_bare_heading_and_no_repeat(report: str) -> None:
    seen: dict[str, str] = {}
    for title, body in _body_sections(report):
        assert lr.has_section_content(body) or "### " in body, f"bare heading: {title}"
        for line in body.splitlines():
            if line.startswith("- ") and "[S" in line:
                assert seen.setdefault(line, title) == title, f"{line!r} in {seen[line]!r} and {title!r}"
        for paragraph in _paragraphs(body):
            assert seen.setdefault(paragraph, title) == title, f"paragraph repeated in {title!r}"


def test_r3_filtered_writers_never_publish_a_bare_heading(tmp_path, bridge):
    """Every writer call blocked by the content filter: all sections fall back
    to their findings; sections sharing a KIQ used to get identical lists that
    deduplication deleted, leaving 'Key Drivers' and 'Signposts' empty."""
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, v3.World(fail=_filtered))
    assert rc == 0, meta.get("error")
    report, qa = _report(out), _qa(out)
    assert len(meta["synthesis_fallback_sections"]) == 8
    assert not meta.get("cross_section_duplicates_removed")
    _assert_no_bare_heading_and_no_repeat(report)
    plan = json.loads((out / "v3" / "plan.json").read_text(encoding="utf-8"))
    headings = [t for t, _ in _body_sections(report)][1:]
    assert headings == [s["title"] for s in plan["sections"] if s["title"] not in qa["dropped_sections"]]


class DuplicatingWorld(v3.World):
    """Every 'Demand Drivers' writer reply (the section's own call and its QA
    repair) copies the 'Market Baseline' analysis word for word."""

    def writer(self, call):
        task = call["messages"][-1][1]
        if "## Demand Drivers\n" not in task:
            return super().writer(call)
        context = call["messages"][2][1]
        sids = re.findall(r"^\[S(\d+)\]", context.split("SOURCE INDEX", 1)[-1], re.M) or ["1"]
        seed = int(hashlib.sha1(b"Market Baseline").hexdigest(), 16)
        body = "\n\n".join(self.paragraph("Market Baseline", seed + k, f"[S{sids[(seed + k) % len(sids)]}]")
                           for k in (0, 1))
        return v3.ai(f"## Demand Drivers\n\n{body}", out=1500)


def test_r3_a_section_emptied_by_deduplication_is_rebuilt_never_repeated(tmp_path, bridge):
    rc, meta, plog, _, out = v3.run_engine(tmp_path, bridge, DuplicatingWorld())
    assert rc == 0, meta.get("error")
    report, qa = _report(out), _qa(out)
    _assert_no_bare_heading_and_no_repeat(report)
    sections = dict(_body_sections(report))
    assert "Demand Drivers" in sections and "Demand Drivers" not in qa["dropped_sections"]
    assert any("emptied by deduplication; rebuilt from unused findings" in m for m in plog.of("warn"))


def test_r3_qa_deduplication_keeps_the_original_over_a_rewrite_that_copies_it():
    copied = ("Installed capacity reached 176 GW in 2023 [S1], and grid queues exceed forty months in the "
              "regions the agency surveys, which caps how fast new campuses can connect.")
    engine = types.SimpleNamespace(bridge_call=lambda name, *args: getattr(v3.dr, name)(*args))
    sections = [{"index": 1, "title": "Repaired", "origin": "repair", "body": f"Own analysis [S2].\n\n{copied}"},
                {"index": 2, "title": "Original", "origin": "writer", "body": copied}]
    assert lr._Engine._dedup(engine, sections, rewrites_last=True) == 1
    assert sections[0]["body"] == "Own analysis [S2]." and sections[1]["body"] == copied


def test_r3_render_report_omits_a_section_without_content():
    report = lr.render_report("Q?", "English", "Summary.", [
        {"index": 1, "title": "Kept", "is_scenario": False, "body": "Body text."},
        {"index": 2, "title": "Bare", "is_scenario": False, "body": "### Only a sub-heading"},
        {"index": 3, "title": "Empty", "is_scenario": False, "body": ""},
        {"index": 4, "title": "Scenarios and Probabilities", "is_scenario": True, "body": ""}], FRAME_EN)
    assert re.findall(r"^## (.+)$", report, re.M) == ["Executive Summary", "Kept", "Scenarios and Probabilities"]


# =============================================================== C15 scenario section

def _plan(titles, *, flags=(), language="English"):
    preset = lr.resolve_preset("standard", {})
    sections = [{"title": t, "kiqs": [1], "focus": "f", **({"scenario": True} if t in flags else {})}
                for t in titles]
    raw = {"kiqs": [{"question": "What is installed capacity?", "queries": ["q"]},
                    {"question": "What drives demand?", "queries": ["q"]}], "sections": sections}
    return lr.build_plan("Q?", language, "2026-09-27", preset, 20, {}, raw)


@pytest.mark.parametrize("titles, language, expected", [
    (["Market Baseline", "Deployment Scenarios and Use Cases", "Key Players", "Scenarios and Probabilities",
      "Signposts to Watch"], "English", "Scenarios and Probabilities"),
    (["市场基线", "人工智能应用场景与算力需求", "主要参与方", "情景与概率", "观察信号"], "Chinese", "情景与概率"),
    (["Market", "Geopolitical Scenario", "Scenario Analysis", "Outlook"], "English", "Scenario Analysis"),
    (["Market", "Application Scenarios", "Outlook"], "English", "Scenarios and Probabilities"),
    (["市场基线", "典型应用场景", "主要参与方"], "Chinese", "情景与概率"),
])
def test_r3_scenario_section_is_the_best_scenario_title_not_a_use_case(titles, language, expected):
    plan = _plan(titles, language=language)
    assert [s.title for s in plan.sections if s.is_scenario] == [expected]


def test_r3_the_planner_designated_scenario_section_wins():
    plan = _plan(["Market", "Scenarios and Probabilities", "Our Forecast View"], flags=("Our Forecast View",))
    assert [s.title for s in plan.sections if s.is_scenario] == ["Our Forecast View"]
    assert '"scenario": true' in lr._render(lr._T_PLAN, min_kiqs=4, max_kiqs=7, min_sections=8, max_sections=12,
                                            language="English", actor_cap=20)


class UseCaseWorld(v3.World):
    SECTIONS = ["Market Baseline", "Deployment Scenarios and Use Cases", "Key Players", "Grid Constraints",
                "Scenarios and Probabilities", "Signposts to Watch"]

    def plan(self, call):
        text = super().plan(call).content
        if self.zh():
            text = text.replace("需求驱动", "人工智能应用场景与算力需求")
        return v3.ai(text)


@pytest.mark.parametrize("language, use_case, scenario_title, block", [
    ("English", "Deployment Scenarios and Use Cases", "Scenarios and Probabilities",
     "### Scenario Probability Distribution"),
    ("Chinese", "人工智能应用场景与算力需求", "情景与概率", "### 情景概率分布"),
])
def test_r3_canonical_block_lands_in_the_real_scenario_section(tmp_path, bridge, language, use_case,
                                                                scenario_title, block):
    world = UseCaseWorld(language=language)
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, world,
                                            **({"question": ZH_QUESTION} if language == "Chinese" else {}))
    assert rc == 0, meta.get("error")
    sections = dict(_body_sections(_report(out)))
    assert block in sections[scenario_title] and block not in sections[use_case]
    for call in v3.calls_of(model, "SECTION WRITING TASK"):
        task = call["messages"][-1][1]
        if f"## {use_case}\n" in task and f"## {scenario_title}\n" not in task:
            assert lr._SCENARIO_SECTION_NOTE not in task


# =============================================================== C14/C23 scenario weights

@pytest.mark.parametrize("frame, text, expected", [
    (FRAME_EN, "We put the Base case at 35%, Accelerated build-out at 45% and Stalled expansion at 20%.",
     "We put the Base case at 50%, Accelerated build-out at 30% and Stalled expansion at 20%."),
    (FRAME_EN, "The Base case carries a 45% probability.", "The Base case carries a 50% probability."),
    (FRAME_EN, "Base case probability: 45%.", "Base case probability: 50%."),
    (FRAME_EN, "We assign a 45% probability to the Base case.", "We assign a 50% probability to the Base case."),
    (FRAME_EN, "Base case (~45%) and Base case (about 45%)", "Base case (~50%) and Base case (about 50%)"),
    (FRAME_EN, "The Base case (p=0.45) leads.", "The Base case (p=0.5) leads."),
    (FRAME_EN, "- Base case: 45%\n- Accelerated build-out — 35% — faster",
     "- Base case: 50%\n- Accelerated build-out — 30% — faster"),
    (FRAME_EN, "The Base case: 45% probability, the most likely path.",
     "The Base case: 50% probability, the most likely path."),
    (FRAME_ZH, "我们判断基准情景概率为35%，加速扩张概率为45%，扩张停滞概率为20%。",
     "我们判断基准情景概率为50%，加速扩张概率为30%，扩张停滞概率为20%。"),
    (FRAME_ZH, "基准情景概率为45%，加速扩张为35%。", "基准情景概率为50%，加速扩张为30%。"),
    (FRAME_ZH, "基准情景的概率约为45%。", "基准情景的概率约为50%。"),
    (FRAME_ZH, "我们给予基准情景45%的概率。", "我们给予基准情景50%的概率。"),
    (FRAME_ZH, "基准情景（概率约45%）、基准情景（约45%）与基准情景（概率为45%）",
     "基准情景（概率约50%）、基准情景（约50%）与基准情景（概率为50%）"),
])
def test_r3_unambiguous_weight_restatements_are_made_equal_to_the_frame(frame, text, expected):
    fixed, fixes = lr.fix_scenario_weights(text, frame)
    assert fixed == expected and fixes


@pytest.mark.parametrize("frame, text", [
    (FRAME_EN, "In the Base case, utilisation reaches 85%."),
    (FRAME_EN, "The Base case at 12%, driven by AI demand, is the growth path."),
    (FRAME_EN, "Base case at 35% utilisation."),
    (FRAME_EN, "If grid queues clear, the Base case would fall to 35%."),
    (FRAME_EN, "If grid queues clear, the Base case probability is 35%."),
    (FRAME_EN, "The Base case probability would rise to 60% if permits accelerate."),
    (FRAME_EN, "Growth by scenario — Base case: 12%; Accelerated build-out: 18%."),
    (FRAME_EN, "The Base case (2.5% annual demand growth [S7]) assumes current policy."),
    (FRAME_ZH, "若电网排队缩短，基准情景概率将升至60%。"),
    (FRAME_ZH, "基准情景下增速为12%。"),
    (FRAME_ZH, "我们将基准情景概率从50%下调至35%。"),
])
def test_r3_other_percentages_and_conditional_analysis_are_never_rewritten(frame, text):
    assert lr.fix_scenario_weights(text, frame) == (text, [])


def test_r3_qa_flags_a_probability_restatement_it_cannot_rewrite():
    assert lr.scenario_weight_conflicts("The Base case, which we consider most likely, carries 45% probability "
                                        "overall.", FRAME_EN)
    assert lr.scenario_weight_conflicts("市场普遍认为基准情景仍有约45%的可能性。", FRAME_ZH)
    for text in ("The Base case (50% probability) assumes a 20% chance of a moratorium.",
                 "If queues clear, the Base case probability would be 35%.",
                 "The Base case probability was raised to 60% after the ruling.",
                 "- **Base case (50% probability):** Trends continue."):
        assert lr.scenario_weight_conflicts(text, FRAME_EN) == [], text


class ProseWeightsWorld(v3.World):
    def __init__(self, *args, exec_text: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.exec_text = exec_text

    def exec_summary(self, call):
        leads = call["messages"][2][1]
        sid = (re.findall(r"\[S(\d+)\]", leads) or ["1"])[0]
        heading = "执行摘要" if self.zh() else "Executive Summary"
        return v3.ai(f"## {heading}\n\n" + (self.exec_text.replace("{sid}", sid) + " ") * 3)


@pytest.mark.parametrize("language, exec_text, restated", [
    ("English", "Capacity reached 176 GW in 2023 [S{sid}]. We put the Base case at 35%, Accelerated build-out at "
                "45% and Stalled expansion at 20%.", "Base case at 50%, Accelerated build-out at 30%"),
    ("Chinese", "装机容量2023年达176吉瓦[S{sid}]。我们判断基准情景概率为35%，加速扩张概率为45%，扩张停滞概率为20%。",
     "基准情景概率为50%，加速扩张概率为30%"),
])
def test_r3_the_summary_restates_the_frame_the_simulation_uses(tmp_path, bridge, language, exec_text, restated):
    world = ProseWeightsWorld(language=language, exec_text=exec_text)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, world,
                                        **({"question": ZH_QUESTION} if language == "Chinese" else {}))
    assert rc == 0, meta.get("error")
    report, qa = _report(out), _qa(out)
    summary = report.split("\n## ", 2)[1]
    assert restated in summary and "35%" not in summary and "45%" not in summary
    fixes = [r for r in qa["repaired"] if r.get("action") == "restated weights corrected"]
    assert fixes and {f["section"] for f in fixes[0]["fixes"]} >= {lr._text(language, "exec_title")}
    assert "scenario_weights_consistent" not in qa["failures"]


def test_r3_an_unrewritable_restatement_fails_the_weight_check(tmp_path, bridge):
    world = ProseWeightsWorld(exec_text="Capacity reached 176 GW in 2023 [S{sid}]. The Base case, which we "
                                        "consider most likely, carries 45% probability overall.")
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, world)
    assert rc == 0, meta.get("error")
    check = next(c for c in _qa(out)["checks"] if c["name"] == "scenario_weights_consistent")
    assert check["passed"] is False and "carries 45% probability overall" in check["detail"]


def test_r3_a_writer_invented_scenario_loses_its_probability(tmp_path, bridge):
    for language in ("English", "Chinese"):
        run_dir = tmp_path / language
        rc, meta, _, _, out = v3.run_engine(run_dir, bridge, v3.World(language=language),
                                            **({"question": ZH_QUESTION} if language == "Chinese" else {}))
        assert rc == 0, meta.get("error")
        report, qa = _report(out), _qa(out)
        name, row = (("尾部风险", "- 尾部风险：极端情形。") if language == "Chinese"
                     else ("Tail risk", "- Tail risk: an extreme outcome."))
        assert row in report and f"{name}（5%" not in report and f"{name} (5%" not in report
        removed = [r for r in qa["repaired"] if r.get("action") == "probabilities of scenarios outside the frame "
                                                                    "removed"]
        assert removed and removed[0]["rows"][0]["name"] == name
        parsed = forecast_inputs_from_report_markdown(report)["scenarios"]
        assert len(parsed) == 3


def test_r3_cited_and_frame_rows_keep_their_probability():
    body = ("- **Tail risk (5% probability):** an extreme outcome.\n"
            "- Recession (35% probability) [S4]: NY Fed model.\n"
            "- **Base case (45%):** x\n- Grid collapse (~10%) — rare\n- plain bullet with 5% growth")
    cleaned, names = lr.strip_extra_scenario_probabilities(body, FRAME_EN)
    assert cleaned.splitlines() == ["- Tail risk: an extreme outcome.",
                                    "- Recession (35% probability) [S4]: NY Fed model.",
                                    "- **Base case (45%):** x", "- Grid collapse — rare",
                                    "- plain bullet with 5% growth"]
    assert names == ["Tail risk", "Grid collapse"]


def test_r3_scenario_row_and_probability_checks_are_linear_on_whitespace_runs():
    """Integration review of C14/C23: on a model line with a long whitespace run
    the extra-scenario row pattern (the marker's "\\s+" handing spaces to the
    name), the bound-probability pattern and the weight restatement patterns
    (two "\\s*" around an optional word) took O(k^2): ~8 s, ~1 s and ~2 s for
    6,000 spaces."""
    for frame, text in ((FRAME_EN, "- " + " " * 6_000 + "x"),
                        (FRAME_EN, "- Tail risk (probability" + " " * 6_000 + "x"),
                        (FRAME_EN, "The Base case probability" + " " * 6_000 + "x"),
                        (FRAME_EN, "Base case 45%" + "\t" * 6_000 + "x"),
                        (FRAME_EN, "Base case (probability" + " " * 6_000 + "x"),
                        (FRAME_EN, "Base case probability" + " " * 3_000 + "is" + " " * 3_000 + "x"),
                        (FRAME_ZH, "基准情景概率" + " " * 3_000 + "为" + " " * 3_000 + "x"),
                        (FRAME_EN, "Base case\n" + " \n" * 6_000 + "x")):
        started = time.perf_counter()
        assert lr.strip_extra_scenario_probabilities(text, frame) == (text, [])
        assert lr.scenario_weight_conflicts(text, frame) == []
        assert lr.fix_scenario_weights(text, frame) == (text, [])
        assert time.perf_counter() - started < 0.5, text[:30]


def test_r3_scenario_rows_with_spaced_markup_still_lose_their_probability():
    body = "- **  Tail risk (5% probability):** extreme.\n-   Grid collapse (~10%) — rare"
    cleaned, names = lr.strip_extra_scenario_probabilities(body, FRAME_EN)
    assert cleaned.splitlines() == ["- Tail risk: extreme.", "-   Grid collapse — rare"]
    assert names == ["Tail risk", "Grid collapse"]


# =============================================================== C17 heading drift

@pytest.mark.parametrize("assigned, reply", [
    (["Market Baseline", "Demand Drivers"],
     "## Market Baseline\nBody A\n## Demand Drivers and AI Workload Growth\nBody B"),
    (["Market Baseline", "Demand Drivers"],
     "## Demand Drivers: AI Workload Growth\nBody B\n## Market Baseline\nBody A"),
    (["Market Baseline", "Demand Drivers"], "## Market Baseline\nBody A\n## What Moves Demand\nBody B"),
    (["Grid Constraints and Interconnection Queues", "Key Players"],
     "## Grid Constraints\nBody A\n## Key Players\nBody B"),
    (["市场基线", "需求驱动"], "## 市场基线\nBody A\n## 需求驱动与人工智能负载增长\nBody B"),
    (["A one", "B two", "C three"], "## A one\nBody A\n## Something else\nBody B\n## C three\nBody C"),
])
def test_r3_a_drifted_heading_maps_to_its_own_section(assigned, reply):
    parsed = lr.split_writer_output(reply, assigned)
    assert parsed[assigned[0]] == "Body A" and parsed[assigned[1]] == "Body B"
    assert "###" not in json.dumps(parsed, ensure_ascii=False)


def test_r3_ambiguous_or_out_of_order_headings_are_still_demoted():
    parsed = lr.split_writer_output("## A one\nx\n## C three\nz\n## Aside\ny", ["A one", "B two", "C three"])
    assert parsed == {"A one": "x", "C three": "z\n\n### Aside\n\ny"}
    demoted: list = []
    parsed = lr.split_writer_output("## Market Baseline\nx\n## Demand Drivers and Signposts to Watch\ny",
                                    ["Market Baseline", "Demand Drivers", "Signposts to Watch"], demoted)
    assert parsed == {"Market Baseline": "x\n\n### Demand Drivers and Signposts to Watch\n\ny"}
    assert lr.drop_demoted_twins(parsed, demoted, ["Demand Drivers", "Signposts to Watch"]) == [
        "Demand Drivers and Signposts to Watch"]
    assert parsed == {"Market Baseline": "x"}


class DriftingWorld(v3.World):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, reverse_writer=False, **kwargs)

    def writer(self, call):
        text = super().writer(call).content
        text = text.replace("## Demand Drivers", "## Demand Drivers and AI Workload Growth")
        text = text.replace("## 需求驱动", "## 需求驱动与人工智能负载增长")
        return v3.ai(text, out=1500)


@pytest.mark.parametrize("language", ["English", "Chinese"])
def test_r3_heading_drift_in_a_writer_group_is_neither_glued_nor_written_twice(tmp_path, bridge, monkeypatch,
                                                                              language):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "2")   # groups of two sections
    rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, DriftingWorld(language=language),
                                               **({"question": ZH_QUESTION} if language == "Chinese" else {}))
    assert rc == 0, meta.get("error")
    title = "需求驱动" if language == "Chinese" else "Demand Drivers"
    singles = [c for c in v3.calls_of(model, "SECTION WRITING TASK")
               if f'did not contain a usable "## {title}" section' in c["messages"][-1][1]]
    assert singles == []
    report = _report(out)
    assert "负载增长" not in report and "AI Workload Growth" not in report
    assert not meta.get("cross_section_duplicates_removed")
    _assert_no_bare_heading_and_no_repeat(report)


# =============================================================== writer retry (gateway follow-up)

def _writer_result(finish: str, cap: int) -> rg.GatewayResult:
    return rg.GatewayResult(message=None, text="Partial analysis [S1].", tool_calls=[], finish_reason=finish,
                            truncated=True, usage={}, served_by="primary", output_cap=cap)


@pytest.mark.parametrize("first, expected_caps, retries", [
    (_writer_result("network_error", 12000), [], [None]),        # aborted part-way: never widened
    (_writer_result("length", 24000), [24000], [None, 32000]),     # the gateway already widened to 24k
    (_writer_result("length", 32000), [32000], [None]),            # already at the writer ceiling
    (_writer_result("length", 12000), [12000], [None, 24000]),
])
def test_r3_writer_retry_counts_from_the_cap_sent_and_never_widens_an_aborted_reply(first, expected_caps,
                                                                                   retries):
    sent: list = []
    seen: list = []

    def invoke(messages, *, kind, label, deadline, max_tokens=None):
        sent.append(max_tokens)
        return first if len(sent) == 1 else _writer_result("stop", max_tokens)

    def wider_cap(kind, messages, deadline, *, ceiling, cap=None):
        seen.append(cap)
        value = min(2 * (cap or 12000), ceiling)
        return value if value > (cap or 12000) else None

    engine = types.SimpleNamespace(gateway=types.SimpleNamespace(invoke=invoke), _wider_cap=wider_cap,
                                   log=lambda kind, message: None)
    result = lr._Engine._write_call(engine, ["m"], label="synth:s1", deadline=None)
    assert seen == expected_caps and sent == retries
    assert result is first if len(retries) == 1 else result.finish_reason == "stop"


def _cut_result(text: str, finish: str, cap: int) -> rg.GatewayResult:
    return rg.GatewayResult(message=None, text=text, tool_calls=[], finish_reason=finish, truncated=True,
                            usage={}, served_by="primary", output_cap=cap)


@pytest.mark.parametrize("first, expected_caps, sent_caps", [
    (_cut_result("## Findings\n- Capacity 176 GW [S1]", "network_error", 6000), [], [None]),   # aborted
    (_cut_result("## Findings\n- Capacity 176 GW [S1]", "length", 12000), [12000], [None]),   # gateway widened
    (_cut_result("## Findings\n- Capacity 176 GW [S1]", "length", 6000), [6000], [None, 12000]),
])
def test_r3_agent_retry_counts_from_the_cap_sent_and_never_widens_an_aborted_reply(first, expected_caps,
                                                                                  sent_caps):
    """Integration review (gateway follow-ups a/b on the agent path): the agent
    re-sent the gateway's own widened request, and widened aborted replies."""
    sent: list = []
    seen: list = []

    def invoke(messages, *, kind, label, tools, deadline, max_tokens=None):
        sent.append(max_tokens)
        return first if len(sent) == 1 else _cut_result("## Findings\n- x [S1]", "stop", max_tokens)

    def wider_cap(messages, cap=None):
        seen.append(cap)
        value = min(2 * (cap or 6000), lr.AGENT_RETRY_MAX_TOKENS)
        return value if value > (cap or 6000) else None

    agent = types.SimpleNamespace(engine=types.SimpleNamespace(gateway=types.SimpleNamespace(invoke=invoke),
                                                               log=lambda kind, message: None),
                                  deadline=None, _wider_cap=wider_cap)
    result = lr.KiqAgent._ask(agent, ["m"], "K1:s2")
    assert seen == expected_caps and sent == sent_caps
    assert result is first if len(sent_caps) == 1 else result.finish_reason == "stop"


def _extraction_engine(invoke, seen: list):
    def wider_cap(kind, messages, deadline, *, ceiling, cap=None):
        seen.append(cap)
        value = min(2 * cap, ceiling)
        return value if value > cap else None

    return types.SimpleNamespace(gateway=types.SimpleNamespace(invoke=invoke), _wider_cap=wider_cap,
                                 log=lambda kind, message: None, extract_cap=32000)


def test_r3_extraction_cut_before_any_text_after_the_gateway_retry_is_not_repaired():
    """Integration review (gateway follow-up c): a reply the cap cut before any
    text even at the gateway's wider cap became ("", not truncated) and paid a
    repair retry that is cut the same way (four calls, two at 64k)."""
    sent: list = []

    def invoke(messages, *, kind, label, deadline, max_tokens=None):
        sent.append(max_tokens)
        raise rg.EmptyResponse("reasoning used the whole 64000-token output cap even after a wider retry",
                               truncated=True)

    with pytest.raises(rg.JsonUnparseable):
        lr._Engine.extraction_call(_extraction_engine(invoke, []), ["brief"], "ACTOR EXTRACTION TASK",
                                   label="extract:actors", required=("actors",), deadline=None)
    assert sent == [32000]


def test_r3_extraction_retry_counts_from_the_cap_sent():
    """Integration review (gateway follow-up a on extraction): after the gateway
    widened an empty cut reply to 64k, a reply still cut there was re-sent at
    the same 64k cap."""
    sent: list = []
    seen: list = []

    def invoke(messages, *, kind, label, deadline, max_tokens=None):
        sent.append(max_tokens)
        return _cut_result('{"actors": [{"name": "Grid operator"}, {"name": "Reg', "length", 64000)

    parsed, truncated = lr._Engine.extraction_call(_extraction_engine(invoke, seen), ["brief"],
                                                   "ACTOR EXTRACTION TASK", label="extract:actors",
                                                   required=("actors",), deadline=None)
    assert sent == [32000] and seen == [64000]
    assert truncated is True and parsed["actors"][0]["name"] == "Grid operator"


# =============================================================== C27 parallel QA rewrites

class ParallelCritiqueWorld(v3.World):
    """The critique names three sections (one of them twice); each rewrite
    waits until all three rewrites are in flight, so serial rewrites time out."""

    TITLES = ["Market Baseline", "Key Players", "Signposts to Watch"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Lock()
        self.active = 0
        self.peak = 0
        self.all_in = threading.Event()

    def critique(self, call):
        issues = [{"section_title": title, "issue": f"Too few numbers in {title}", "fix": "Add the baseline"}
                  for title in self.TITLES]
        issues.insert(1, {"section_title": "Market Baseline", "issue": "No 2024 figure", "fix": "Add 2024"})
        return v3.ai(json.dumps({"issues": issues}))

    def writer(self, call):
        if "Problem to fix" not in call["messages"][-1][1]:
            return super().writer(call)
        with self.gate:
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active >= len(self.TITLES):
                self.all_in.set()
        try:
            self.all_in.wait(timeout=3.0)
            return super().writer(call)
        finally:
            with self.gate:
                self.active -= 1


def test_r3_qa_critique_rewrites_run_together_after_a_prime(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_CRITIQUE", "1")
    world = ParallelCritiqueWorld()
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, world)
    assert rc == 0, meta.get("error")
    assert world.peak == 3                                   # all three rewrites were in flight at once
    roles = [v3.role_of(c) for c in model.calls]
    critique_at = roles.index("CRITIQUE TASK")
    rewrites = [i for i, c in enumerate(model.calls) if "Problem to fix" in c["messages"][-1][1]]
    assert len(rewrites) == 3                                # one rewrite per section, issues merged
    primes = [i for i in range(critique_at, rewrites[0]) if roles[i] == "prime"]
    assert primes and model.calls[primes[0]]["messages"][:3] == model.calls[rewrites[0]]["messages"][:3]
    merged = [model.calls[i]["messages"][-1][1] for i in rewrites
              if "## Market Baseline\n" in model.calls[i]["messages"][-1][1]]
    assert len(merged) == 1 and "Too few numbers in Market Baseline" in merged[0] and "No 2024 figure" in merged[0]
    repaired = [r for r in meta["research_qa"]["repaired"] if r["check"] == "critique"]
    assert [r["section"] for r in repaired] == ["Market Baseline", "Market Baseline", "Key Players",
                                               "Signposts to Watch"]


def test_r3_parallel_rewrites_keep_what_finished_when_the_provider_goes_down():
    calls: list[str] = []

    def rewrite(section, context, deadline, *, problem, label):
        calls.append(label)
        if label == "b":
            raise rg.ProviderUnavailable("down")
        return (f"{label} body", False)

    logs: list[tuple[str, str]] = []
    gateway = types.SimpleNamespace(prime=lambda *a, **k: calls.append("prime") or True,
                                    fan_out=lambda jobs, **k: [_run(job) for job in jobs])
    engine = types.SimpleNamespace(
        gateway=gateway, preset=types.SimpleNamespace(workers=4), brief="brief", log=lambda k, m: logs.append((k, m)),
        optional_allowed=lambda *a, **k: True, _rewrite_section=rewrite,
        _rewrite_messages=lambda section, context, problem: rg.build_messages("system", [context], problem))
    jobs = [({"index": i}, "p", label) for i, label in enumerate("abc")]
    result = lr._Engine._parallel_rewrites(engine, jobs, "ctx", None, "QA repairs")
    assert result == [("a body", False), None, ("c body", False)]
    assert calls[0] == "prime" and sorted(calls[1:]) == ["a", "b", "c"]
    assert any("QA repairs stopped (ProviderUnavailable" in message for _, message in logs)


def _run(job):
    try:
        return job()
    except Exception as exc:  # noqa: BLE001 — mirrors ModelGateway.fan_out
        return exc


@pytest.mark.parametrize("pattern, text", [
    ("_MARKER_URL_RE", "S1" + " " * 20000 + "x"),
    ("_EMPTY_PROB_PARENS_RE", "(" + " " * 20000 + "x"),
    ("_PERCENT_FRAGMENT_RE", "1" + " " * 20000 + "x"),
])
def test_r3_scenario_name_and_marker_patterns_are_linear_on_whitespace(pattern, text):
    """These patterns run on model text (tool-call URLs, scenario names); a
    long whitespace run used to cost quadratic time."""
    import time

    compiled = getattr(lr, pattern)
    started = time.perf_counter()
    compiled.match(text) if pattern == "_MARKER_URL_RE" else compiled.search(text)
    assert time.perf_counter() - started < 0.05
