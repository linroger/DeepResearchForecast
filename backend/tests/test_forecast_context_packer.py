"""RESEARCH-13 (P09): the forecast-prompt context packer (pure, offline).

Pins the dated-period parser, the heading classes, the priority fill invariants, the as_of
lanes (past only / newest first / absence line / scheduled guard), the fail-closed temporal
audit, the as_of validation fallback, near-duplicate dossier dedup and, on a pipe_6c41-shaped
dossier, that the pack keeps the resolution-ready section and no References chars where the
legacy 48k head+tail slice drops it.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timezone

import pytest

from app.services import forecast_context_packer as cp
from app.services.forecast_extractor import slice_head_tail

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 9, 15)


def _para(tag: str, n: int) -> str:
    """``n`` chars of distinct prose lines tagged ``tag``, blank-line separated paragraphs."""
    lines, i = [], 0
    while sum(len(x) + 1 for x in lines) < n:
        lines.append(f"{tag} sentence {i} carries some analysis text for the packer fixture.")
        if i % 4 == 3:
            lines.append("")
        i += 1
    return "\n".join(lines)[:n]


# ----------------------------------------------------------------------- dated periods
@pytest.mark.parametrize("raw, start, end, precision", [
    ("2026-03", date(2026, 3, 1), date(2026, 3, 31), "month"),
    ("2026-Q3-Q4", date(2026, 7, 1), date(2026, 12, 31), "quarter"),
    ("2026-Q2", date(2026, 4, 1), date(2026, 6, 30), "quarter"),
    ("2026-H2", date(2026, 7, 1), date(2026, 12, 31), "half"),
    ("2026-07-23", date(2026, 7, 23), date(2026, 7, 23), "day"),
    ("2026/07/23", date(2026, 7, 23), date(2026, 7, 23), "day"),
    ("2026", date(2026, 1, 1), date(2026, 12, 31), "year"),
    ("2026年3月5日", date(2026, 3, 5), date(2026, 3, 5), "day"),
    ("2026年3月", date(2026, 3, 1), date(2026, 3, 31), "month"),
    ("2026年第三季度", date(2026, 7, 1), date(2026, 9, 30), "quarter"),
    ("2026年上半年", date(2026, 1, 1), date(2026, 6, 30), "half"),
    ("2026年下半年", date(2026, 7, 1), date(2026, 12, 31), "half"),
])
def test_parse_dated_period_forms(raw, start, end, precision):
    assert cp.parse_dated_period(raw) == cp.DatedPeriod(start, end, precision)


@pytest.mark.parametrize("raw", [None, "", "   ", "TBD", "soon", "late in the decade", True])
def test_parse_dated_period_garbage_is_undated(raw):
    assert cp.parse_dated_period(raw) is None


def test_temporal_class_gates_on_the_period_end():
    assert cp.temporal_class(cp.parse_dated_period("2026-09-15"), AS_OF) == "past"
    assert cp.temporal_class(cp.parse_dated_period("2026-08"), AS_OF) == "past"
    assert cp.temporal_class(cp.parse_dated_period("2026-09"), AS_OF) == "straddle"
    assert cp.temporal_class(cp.parse_dated_period("2026-Q3"), AS_OF) == "straddle"
    assert cp.temporal_class(cp.parse_dated_period("2026-09-16"), AS_OF) == "future"
    assert cp.temporal_class(cp.parse_dated_period("2027"), AS_OF) == "future"
    assert cp.temporal_class(None, AS_OF) == "undated"


# ----------------------------------------------------------------------- heading classes
@pytest.mark.parametrize("heading, cls", [
    ("References", "excluded"),
    ("References (S1–S40)", "excluded"),
    ("Visual Annex", "excluded"),
    ("How to Read This Dossier", "excluded"),
    ("参考文献", "excluded"),
    ("参考来源", "excluded"),
    ("六、参考资料(References)", "excluded"),
    ("十一、来源清单（References）", "excluded"),
    ("图表附录", "excluded"),
    ("阅读说明", "excluded"),
    ("Sources", "appendix"),
    ("12. Sources", "appendix"),
    ("Sources, Methodology & Confidence Tiering", "appendix"),
    ("Source Manifest & Source-Tier Discipline (Part 3 Appendix)", "appendix"),
    ("第八章 来源（Sources）", "appendix"),
    ("来源分级与方法论透明度附录", "appendix"),
    ("附录B：协议核心条款对照表", "appendix"),
    ("Methodology", "appendix"),
    ("Executive Summary", "executive_summary"),
    ("一、执行摘要（Executive Summary）", "executive_summary"),
    ("摘要(Executive Summary)", "executive_summary"),
    ("Resolution-ready forecasts and indicators to watch", "analyst_forecasts"),
    ("Binary Forecasts — 10 Resolvable Yes/No Questions", "analyst_forecasts"),
    ("PART 1 — THE FORECASTS", "analyst_forecasts"),
    ("Part 1: Your Forecasts", "analyst_forecasts"),
    ("可判定的二元预测", "analyst_forecasts"),
    ("判定标准与观察指标", "analyst_forecasts"),
    ("Scenarios and Forecast Implications", "scenario"),
    ("附录A：概率情景汇总表", "scenario"),
    ("六、情景分析：Base / Upside / Downside（2026–2030）", "scenario"),
    ("Reference-Class Base Rates & Historical Anchoring", "body"),
    ("Sources of Growth in the Memory Cycle", "body"),
    ("Track 1: 基率·参照类·历史类比 (Base Rates & Reference Classes)", "body"),
    ("Key Actors and Incentives", "body"),
])
def test_classify_heading_bilingual(heading, cls):
    assert cp.classify_heading(heading) == cls


def test_split_h2_is_fence_aware_and_keeps_h3_with_its_h2():
    md = ("Preamble line.\n\n# Title\n\nIntro.\n\n## Executive Summary\n\nSummary.\n\n"
          "### Sub point\n\nDetail.\n\n```\n## not a heading\n```\n\n## References\n\n[S1] x\n")
    sections = cp.split_h2(md)
    assert [(s.level, s.heading) for s in sections] == [
        (0, ""), (1, "Title"), (2, "Executive Summary"), (2, "References")]
    summary = sections[2]
    assert summary.cls == "executive_summary"
    assert "### Sub point" in summary.text and "## not a heading" in summary.text
    assert sections[3].cls == "excluded"


# ----------------------------------------------------------------------- priority fill
def _streams(seed: int):
    rng = random.Random(seed)
    return [(name, [_para(f"{name}{i}", rng.randint(50, 4000)) for i in range(rng.randint(0, 4))])
            for name in ("a", "b", "c", "d")]


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("budget", [0, 500, 3000, 9000, 40000])
def test_priority_fill_invariants(seed, budget):
    caps = {"a": 0.35, "b": 0.15, "c": 0.2}  # "d" is leftover-only
    streams = _streams(seed)
    first = cp.priority_fill(streams, budget, caps)
    assert first == cp.priority_fill(streams, budget, caps)  # deterministic
    total_alloc = 0
    for name, pieces in streams:
        tel = first.telemetry[name]
        kept_text = "\n\n".join(text for _idx, text in first.kept[name])
        assert tel["kept_chars"] <= tel["allocated_chars"] <= tel["raw_chars"]
        assert len(kept_text) <= tel["allocated_chars"]
        assert tel["sections_kept"] + tel["sections_dropped"] == len(pieces)
        # whole pieces in document order; only the last kept one may be truncated
        for pos, (idx, text) in enumerate(first.kept[name]):
            assert idx == pos
            if text != pieces[idx]:
                assert pos == len(first.kept[name]) - 1 and text.endswith("…[truncated]")
                assert tel["truncated"] is True
        total_alloc += tel["allocated_chars"]
    assert total_alloc <= budget


def test_priority_fill_leftover_goes_in_priority_order():
    streams = [("a", [_para("a", 5000)]), ("b", [_para("b", 5000)]), ("c", [_para("c", 5000)])]
    caps = {"a": 0.1, "b": 0.1, "c": 0.1}
    fill = cp.priority_fill(streams, 10000, caps)
    # pass 1 gives 1,000 each; the 7,000 leftover goes to "a" first (it still has raw chars)
    assert fill.telemetry["a"]["allocated_chars"] == 1000 + 4002
    assert fill.telemetry["b"]["allocated_chars"] == 1000 + 2998
    assert fill.telemetry["c"]["allocated_chars"] == 1000
    # a stream without a cap only receives leftover
    leftover_only = cp.priority_fill([("a", ["x" * 100]), ("z", ["y" * 5000])], 1000, {"a": 1.0})
    assert leftover_only.telemetry["z"]["allocated_chars"] == 1000 - 102


def test_priority_fill_cuts_at_a_line_boundary_and_skips_tiny_partials():
    piece = "\n".join(f"line {i:03d} " + "x" * 40 for i in range(40))
    fill = cp.priority_fill([("s", [piece])], 700, {"s": 1.0})
    (idx, text), = fill.kept["s"]
    assert text.endswith("\n…[truncated]")
    body = text[: -len("\n…[truncated]")]
    assert piece.startswith(body) and piece[len(body)] == "\n"
    tiny = cp.priority_fill([("s", ["h" * 10 + "\n" + "y" * 400])], 60, {"s": 1.0})
    assert tiny.kept["s"] == [] and tiny.telemetry["s"]["sections_dropped"] == 1


# ----------------------------------------------------------------------- lanes
TIMELINE = [
    {"date": "2026-03-09", "event": "Older event from March."},
    {"date": "2026-07-23", "event": "Newest past event: the July announcement."},
    {"date": "2026-09", "event": "September straddling event."},
    {"date": "", "event": "Undated background item."},
    {"date": "2026-05", "event": "May month-level item."},
    {"date": "2026-10-20", "event": "Scheduled October summit."},
    {"date": "2026-07-23", "event": "Newest past event: the July announcement."},
    {"date": "2025", "event": "Last year's baseline."},
]


def test_straddling_row_is_excluded_from_the_lane():
    lane = cp.developments_lane([{"date": "2026-09", "event": "Month of September row"}], AS_OF)
    assert lane.items == () and lane.stats["straddle"] == 1
    assert "September row" not in lane.render()


def test_lane_is_newest_first_deduplicated_and_rendered_with_ages():
    lane = cp.developments_lane(TIMELINE, AS_OF)
    assert [i.date for i in lane.items] == ["2026-07-23", "2026-05", "2026-03-09", "2025"]
    assert lane.stats["duplicates"] == 1 and lane.stats["undated"] == 1
    assert lane.stats["straddle"] == 1 and lane.stats["future"] == 1
    assert lane.lines[0] == "- 2026-07-23 (54 days before as-of): Newest past event: the July announcement."
    assert lane.render().startswith(
        "[DEVELOPMENTS — events dated on or before 2026-09-15; newest first; "
        "event dates only, source availability not verified]\n")


def test_pack_sha_is_permutation_invariant():
    report = "## Executive Summary\n\n" + _para("exec", 800) + "\n\n## Body\n\n" + _para("body", 900)
    shuffled = list(TIMELINE)
    random.Random(7).shuffle(shuffled)
    a = cp.build_binary_pack(report, TIMELINE, "2026-09-15", NOW, 48000)
    b = cp.build_binary_pack(report, shuffled, "2026-09-15", NOW, 48000)
    assert a.ok and a.text == b.text
    assert a.text_sha256 == b.text_sha256 and a.input_sha256 == b.input_sha256
    s1 = cp.build_spine_pack(report, "brief", "metrics", TIMELINE, "2026-09-15", NOW, 14000)
    s2 = cp.build_spine_pack(report, "brief", "metrics", shuffled, "2026-09-15", NOW, 14000)
    assert s1.text_sha256 == s2.text_sha256 and s1.input_sha256 == s2.input_sha256


def test_absence_line_when_nothing_is_eligible():
    lane = cp.developments_lane([{"date": "2026-09", "event": "straddle"},
                                 {"date": "", "event": "undated"},
                                 {"date": "2027-01-01", "event": "future"}], AS_OF)
    assert lane.items == ()
    assert lane.render().endswith(
        "no dated development on or before 2026-09-15 in the research timeline "
        "(1 undated, 1 straddling)")
    zh = cp.developments_lane([], AS_OF, lang="zh")
    assert "研究时间线中没有日期在 2026-09-15 当日或之前的进展" in zh.render()


def test_scheduled_rows_shown_live_and_withheld_retrospectively():
    live_as_of = (NOW.date().toordinal() - 1)
    live = cp.scheduled_lane(TIMELINE, date.fromordinal(live_as_of), NOW, 30)
    assert [i.date for i in live.items] == ["2026-10-20"]
    assert live.render().startswith(
        "[SCHEDULED — dated after 2026-09-29: not yet occurred; catalysts, not evidence]")
    assert live.stats["post_as_of_rows_withheld"] == 0
    old_as_of = date.fromordinal(NOW.date().toordinal() - 400)
    rows = [{"date": "2026-01-10", "event": "After the old as_of."},
            {"date": "2026-02-10", "event": "Also after it."}]
    withheld = cp.scheduled_lane(rows, old_as_of, NOW, 30)
    assert withheld.items == () and withheld.render() == ""
    assert withheld.stats["guard"] == "withheld" and withheld.stats["post_as_of_rows_withheld"] == 2
    packed = cp.build_binary_pack("## Body\n\n" + _para("b", 500), rows, old_as_of.isoformat(),
                                  NOW, 48000)
    assert "[SCHEDULED" not in packed.text and "After the old as_of" not in packed.text
    assert packed.telemetry["lanes"]["scheduled"]["post_as_of_rows_withheld"] == 2


def test_forged_item_withholds_its_segment():
    honest = cp.developments_lane(TIMELINE, AS_OF)
    forged_item = cp.LaneItem("2026-12-01", "A future event presented as past", -77)
    forged = cp.Segment(honest.name, honest.contract, honest.header,
                        honest.items + (forged_item,), honest.lines, "", honest.stats)
    kept, violations = cp.audit_temporal_contract([forged, honest], AS_OF)
    assert kept == [honest]
    assert violations == [{"segment": "developments", "contract": "on_or_before",
                           "date": "2026-12-01", "class": "future",
                           "event_head": "A future event presented as past"}]


def test_forged_lane_is_never_emitted_by_a_pack(monkeypatch):
    real = cp.developments_lane

    def forging(timeline, as_of, **kwargs):
        seg = real(timeline, as_of, **kwargs)
        bad = cp.LaneItem("2027-01-01", "Leaked future row", -108)
        return cp.Segment(seg.name, seg.contract, seg.header, seg.items + (bad,),
                          seg.lines + ("- 2027-01-01 (-108 days before as-of): Leaked future row",),
                          seg.absence, seg.stats)

    monkeypatch.setattr(cp, "developments_lane", forging)
    result = cp.build_binary_pack("## Body\n\n" + _para("b", 600), TIMELINE, "2026-09-15", NOW)
    assert result.ok
    assert "[DEVELOPMENTS" not in result.text and "Leaked future row" not in result.text
    audit = result.telemetry["lanes"]["audit"]
    assert audit["withheld_segments"] == ["developments"]
    assert [v["date"] for v in audit["violations"]] == ["2027-01-01"]


@pytest.mark.parametrize("as_of_raw", [None, "", "2026-07", "2026", "2026-Q3", "garbage",
                                       "2026-10-01", "2026-02-30"])
def test_invalid_or_future_as_of_falls_back(as_of_raw):
    report = "## Executive Summary\n\n" + _para("e", 400)
    binary = cp.build_binary_pack(report, TIMELINE, as_of_raw, NOW, 48000)
    spine = cp.build_spine_pack(report, "brief", "", TIMELINE, as_of_raw, NOW, 14000)
    for result in (binary, spine):
        assert result.status == cp.STATUS_AS_OF_INVALID and result.text == "" and not result.ok


def test_non_positive_budget_falls_back():
    report = "## Executive Summary\n\n" + _para("e", 400)
    assert cp.build_binary_pack(report, TIMELINE, "2026-09-15", NOW, 0).status == \
        cp.STATUS_BUDGET_INVALID
    assert cp.build_spine_pack(report, "", "", TIMELINE, "2026-09-15", NOW, -5).status == \
        cp.STATUS_BUDGET_INVALID


def test_dossier_without_h2_falls_back_to_the_legacy_slice():
    report = "# Title\n\n" + _para("flat", 60000)
    result = cp.build_binary_pack(report, TIMELINE, "2026-09-15", NOW, 48000)
    assert result.status == cp.STATUS_NO_H2 and not result.ok
    assert result.text == slice_head_tail(report, 48000)


def test_split_chronology_separates_past_and_scheduled():
    split = cp.split_chronology(TIMELINE, date(2026, 9, 25), NOW, max_past=3, window_days=30)
    assert [r["date"] for r in split["past"]] == ["2026-03-09", "2026-05", "2026-07-23"]
    assert split["scheduled"] == [{"date": "2026-10-20", "event": "Scheduled October summit."}]
    assert split["undated"] == 1 and split["straddle"] == 1
    retro = cp.split_chronology(TIMELINE, date(2025, 6, 1), NOW, window_days=30)
    assert retro["scheduled"] == [] and retro["post_as_of_rows_withheld"] == 6


# ----------------------------------------------------------------------- dossier packs
def _pipe_6c41_dossier() -> str:
    """Exec summary, long body, the analyst's resolution-ready section in the middle, then
    ~24k of References and a Visual Annex: the tail of the legacy slice is all bibliography."""
    refs = "\n".join(f"[S{i}] Source title number {i} — https://example.org/doc/{i}"
                     for i in range(1, 460))
    return "\n\n".join([
        "# Quantum computing to 2040: forecast dossier",
        "## Executive Summary\n\n" + _para("exec", 3000),
        "## 1. Baseline hardware state\n\n" + _para("baseline", 16000),
        "## 2. National programmes\n\n" + _para("programmes", 16000),
        "## Resolution-ready forecasts and indicators to watch\n\n"
        "| # | Statement | P |\n|---|---|---|\n| F1 | Logical qubits exceed 100 by 2030 | 0.35 |\n"
        + _para("resolution", 4000),
        "## 3. Supply chain\n\n" + _para("supply", 14000),
        "## Scenarios and probabilities\n\n" + _para("scenario", 5000),
        "## References\n\n" + refs[:24000],
        "## Visual Annex\n\n" + _para("annex", 3000),
    ])


def test_pipe_6c41_shape_keeps_resolution_section_and_no_references():
    report = _pipe_6c41_dossier()
    legacy = slice_head_tail(report, 48000)
    assert "## Resolution-ready forecasts" not in legacy
    # the legacy tail is bibliography
    assert sum(line.startswith("[S") for line in legacy.split("\n")) > 200
    result = cp.build_binary_pack(report, TIMELINE, "2026-09-15", NOW, 48000)
    assert result.ok and result.status == cp.STATUS_OK
    assert "## Resolution-ready forecasts and indicators to watch" in result.text
    assert "| F1 | Logical qubits exceed 100 by 2030 | 0.35 |" in result.text
    assert "## Executive Summary" in result.text and "## Scenarios and probabilities" in result.text
    assert "[S1" not in result.text and "## References" not in result.text
    assert "## Visual Annex" not in result.text and "annex sentence" not in result.text
    tel = result.telemetry
    assert tel["sections"]["excluded_headings"] == ["References", "Visual Annex"]
    assert tel["streams"]["analyst_forecasts"]["sections_kept"] == 1
    assert tel["streams"]["analyst_forecasts"]["truncated"] is False
    # the pack follows the lanes, and sections keep document order
    assert result.text.index("[DEVELOPMENTS") < result.text.index("[DOSSIER EXCERPT")
    assert result.text.index("## Executive Summary") < result.text.index("## Resolution-ready")
    excerpt = result.text[result.text.index("[DOSSIER EXCERPT"):]
    assert len(excerpt) <= 48000
    lanes = result.text[: result.text.index("[DOSSIER EXCERPT")]
    assert len(lanes) <= 5000 + 2000  # the budget-exempt lanes stay bounded


def test_duplicate_dossiers_are_deduplicated():
    single = "\n\n".join([
        "# Track dossier",
        "## Executive Summary\n\n" + _para("exec", 1500),
        "## Binary forecasts\n\n" + _para("binary", 1500),
        "## Market structure\n\n" + _para("market", 1500),
    ])
    near = single.replace("exec sentence 3 ", "exec sentence 3 (updated) ")
    result = cp.build_binary_pack(single + "\n\n" + near, TIMELINE, "2026-09-15", NOW, 48000)
    assert result.ok
    assert result.text.count("## Executive Summary") == 1
    assert result.text.count("## Binary forecasts") == 1
    assert result.telemetry["sections"]["duplicates_dropped"] == 4  # H1 title + 3 H2 copies
    # a second dossier with the same headings but different content is kept whole
    rng = random.Random(3)
    other = "\n\n".join([
        "# Track dossier",
        "## Executive Summary\n\n" + " ".join(f"w{rng.randrange(10**6)}" for _ in range(200)),
        "## Binary forecasts\n\n" + " ".join(f"w{rng.randrange(10**6)}" for _ in range(200)),
    ])
    kept = cp.build_binary_pack(single + "\n\n" + other, TIMELINE, "2026-09-15", NOW, 48000)
    assert kept.text.count("## Executive Summary") == 2
    assert kept.text.count("## Binary forecasts") == 2
    assert kept.telemetry["sections"]["duplicates_dropped"] == 1  # only the H1 title repeats


def test_spine_pack_fills_shares_within_budget():
    report = _pipe_6c41_dossier()
    situation = "## 局势简报\n### 当前态势\n" + _para("situation", 6000)
    metrics = "## 关键量化指标\n| 指标 | 数值 |\n|---|---|\n" + "\n".join(
        f"| metric {i} | {i} |" for i in range(400))
    result = cp.build_spine_pack(report, situation, metrics, TIMELINE, "2026-09-15", NOW, 14000)
    assert result.ok and len(result.text) <= 14000
    text = result.text
    assert text.startswith("[研究档案摘录")
    assert "## Executive Summary" in text and "## Scenarios and probabilities" in text
    assert "## Resolution-ready" not in text and "## References" not in text
    assert "[近期进展 — 日期在 2026-09-15 当日或之前的事件" in text
    assert "- 2026-07-23（as-of 前 54 天）：Newest past event" in text
    assert "## 局势简报" in text and "## 关键量化指标" in text
    streams = result.telemetry["streams"]
    for name, share in cp.SPINE_CAPS.items():
        assert streams[name]["kept_chars"] <= streams[name]["allocated_chars"]
        if streams[name]["raw_chars"] > share * 14000:
            assert streams[name]["allocated_chars"] >= int(share * (14000 - 200)) - 1


def test_digest_and_sidecar_shapes():
    result = cp.build_binary_pack(_pipe_6c41_dossier(), TIMELINE, "2026-09-15", NOW)
    digest = result.digest("binary")
    assert digest["schema"] == "drf.context_pack/1" and "text" not in digest
    assert digest["text_sha256"] == result.text_sha256 and digest["text_chars"] == len(result.text)
    assert result.sidecar("binary")["text"] == result.text
