"""W9-8 报告集成回归：昂贵研究产物直通 ReportAgent 的证据块与注入行为。

覆盖（integration agent 中断后由主会话补齐的四个方法 + 注入线）：
- _build_key_metrics_block: quantitative.json 全量 → 关键指标表（层级/时效排序、上限、陈旧标注、竖线转义）
- _build_contested_table_block: 争议论断块（立场⇄立场、上限）
- _build_chronology_block: 紧凑时间线（升序、去重、上限=取最近）
- _kg_structural_note: KG 中心度注记（别名组 MAX 去重、chokepoint 标记、无数据空串）
- _prepend_research_background(section_title=...): 关键词命中才追加对应块
- 构造 kwargs 向后兼容（全部缺省 → None，行为不变）
"""
import pytest

from app.config import Config
from app.services.report_agent import ReportAgent


def _bare_agent(**attrs):
    """__new__ 绕过 __init__（与既有离线测试同一模式），只挂本测试需要的属性。"""
    a = ReportAgent.__new__(ReportAgent)
    defaults = dict(quantitative=None, contested=None, timeline_events=None,
                    graph_priors=None, graph_priors_structural=None)
    defaults.update(attrs)
    for k, v in defaults.items():
        setattr(a, k, v)
    return a


class TestKeyMetricsBlock:
    def test_empty_when_no_data(self):
        assert _bare_agent()._build_key_metrics_block() == ""

    def test_renders_table_sorted_by_tier(self):
        rows = [
            {"metric": "B metric", "value": "5", "unit": "%", "as_of_date": "2026-01-01",
             "tier": "S3", "source": "srcB"},
            {"metric": "A metric", "value": "100", "unit": "USD billion",
             "as_of_date": "2026-05-27", "tier": "S1", "source": "srcA"},
        ]
        out = _bare_agent(quantitative=rows)._build_key_metrics_block()
        assert "| 指标 |" in out
        assert out.index("A metric") < out.index("B metric")  # S1 排在 S3 前

    def test_stale_flag_and_pipe_escape(self):
        rows = [{"metric": "X|Y", "value": "1", "unit": "", "as_of_date": "2024-01-01",
                 "tier": "S2", "source": "s", "is_stale": True}]
        out = _bare_agent(quantitative=rows)._build_key_metrics_block()
        assert "⚠" in out and "X\\|Y" in out

    def test_cap_respected(self, monkeypatch):
        from app.config import Config
        monkeypatch.setattr(Config, "REPORT_KEY_METRICS_MAX", 3, raising=False)
        rows = [{"metric": f"m{i}", "value": str(i), "unit": "", "as_of_date": "2026-01-01",
                 "tier": "S1", "source": "s"} for i in range(10)]
        out = _bare_agent(quantitative=rows)._build_key_metrics_block()
        assert len([l for l in out.split("\n") if l.startswith("| m")]) == 3


class TestContestedBlock:
    def test_empty_when_no_data(self):
        assert _bare_agent()._build_contested_table_block() == ""

    def test_renders_positions(self):
        rows = [{"claim": "Is X viable?", "positions": [
            {"stance": "Yes within 2 years", "sources": ["A 2026-04"], "tier": "S2"},
            {"stance": "No, yields too low", "sources": ["B 2026-06"], "tier": "S1"},
        ]}]
        out = _bare_agent(contested=rows)._build_contested_table_block()
        assert "Is X viable?" in out and "⇄" in out and "S2" in out

    def test_cap(self):
        rows = [{"claim": f"c{i}", "positions": [{"stance": "s", "sources": [], "tier": "S2"}]}
                for i in range(30)]
        out = _bare_agent(contested=rows)._build_contested_table_block(max_claims=15)
        assert sum(1 for l in out.split("\n") if l.startswith("- **")) == 15


# reconcile_quantitative's why_they_differ on a ~1000x gap (deerflow_research.py).
_UNIT_SCALE_WHY = ("quantitative disagreement on 'q' reconciled by (metric,unit); high/low ratio=1000.0"
                   "; ~1000x apart — probable unit-scale error")


def _contested(n_model, n_quant, *, unit_scale=()):
    """n_model model claims, then n_quant quant_reconcile rows (contested.json order of every
    engine); the quant rows whose index is in unit_scale carry the unit-scale marker."""
    model = [{"claim": f"m{i}", "positions": [{"stance": "s", "sources": [], "tier": "S2"}]}
             for i in range(n_model)]
    quant = [{"claim": f"q{i}", "origin": "quant_reconcile",
              "why_they_differ": _UNIT_SCALE_WHY if i in unit_scale else "high/low ratio=1.5",
              "positions": [{"stance": "a", "sources": [], "tier": ""}, {"stance": "b", "sources": [], "tier": ""}]}
             for i in range(n_quant)]
    return model + quant


# Golden bytes of the block as W9-8 renders it (header, then one line per claim; a model row
# here is "s" tagged with its tier, a quant row is "a ⇄ b" with no tag).
_HEADER = "## 争议性关键论断（证据分歧——本章须正面呈现两侧立场与依据，不得单边引用）"


def _golden(model, quant=()):
    return "\n".join([_HEADER] + [f"- **m{i}** — s（S2）" for i in model]
                     + [f"- **q{i}** — a ⇄ b" for i in quant])


@pytest.fixture(params=[True, False], ids=["knob_on", "knob_off"])
def reconcile_knob(request, monkeypatch):
    monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", request.param, raising=False)
    return request.param


class TestContestedQuantSlots:
    """FU-9 (TIME-4 open issue): every engine appends its quantitative disagreements after
    the model's claims, so a plain cut at 15 dropped them all."""

    @pytest.mark.parametrize("unit_scale, kept", [
        ((0, 1), (0, 1, 2)),  # v3 order: the producer already lists unit-scale errors first
        ((2, 3), (2, 3, 0)),  # legacy / extract-only order: metric-group order, so they can come last
        ((1, 3), (1, 3, 0)),
    ], ids=["v3_order", "legacy_order", "mixed_order"])
    def test_reserves_up_to_three_slots_unit_scale_first(self, monkeypatch, unit_scale, kept):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        out = _bare_agent(contested=_contested(20, 4, unit_scale=unit_scale))._build_contested_table_block()
        assert out == _golden(range(12), kept) + "\n（另有 1 条数值对账分歧超出上限未列出）"

    def test_unit_scale_rows_listed_last_still_win_the_slots(self, monkeypatch):
        # Review round 1 probe: picking by position kept q0..q2 and cut both unit-scale errors.
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        out = _bare_agent(contested=_contested(20, 5, unit_scale=(3, 4)))._build_contested_table_block()
        assert out == _golden(range(12), (3, 4, 0)) + "\n（另有 2 条数值对账分歧超出上限未列出）"

    def test_note_counts_unit_scale_errors_still_cut(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        out = _bare_agent(contested=_contested(20, 6, unit_scale=(1, 2, 3, 4, 5)))._build_contested_table_block()
        assert out == (_golden(range(12), (1, 2, 3))
                       + "\n（另有 3 条数值对账分歧超出上限未列出，其中 2 条疑似量纲错误）")

    def test_unit_scale_row_displaces_a_quant_row_inside_the_plain_cut(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        out = _bare_agent(contested=_contested(12, 4, unit_scale=(3,)))._build_contested_table_block()
        assert out == _golden(range(12), (3, 0, 1)) + "\n（另有 1 条数值对账分歧超出上限未列出）"

    def test_one_slot_goes_to_the_top_quant_row(self, monkeypatch):
        # min(_CONTESTED_QUANT_SLOTS, max_claims) slots are reserved, so a single slot is a
        # quant row's when one is cut (with the knob off it stays the first row, m0).
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        out = _bare_agent(contested=_contested(20, 4, unit_scale=(2, 3)))._build_contested_table_block(max_claims=1)
        assert out == _golden((), (2,)) + "\n（另有 3 条数值对账分歧超出上限未列出，其中 1 条疑似量纲错误）"

    def test_nothing_cut_is_byte_identical(self, reconcile_knob):
        out = _bare_agent(contested=_contested(10, 2, unit_scale=(1,)))._build_contested_table_block()
        assert out == _golden(range(10), (0, 1))
        assert _bare_agent(contested=_contested(13, 2))._build_contested_table_block() == _golden(
            range(13), (0, 1))

    def test_no_quant_rows_is_byte_identical(self, reconcile_knob):
        assert _bare_agent(contested=_contested(20, 0))._build_contested_table_block() == _golden(range(15))

    def test_quant_rows_inside_the_plain_cut_is_byte_identical(self, reconcile_knob):
        # Only model claims are cut: no quant row is lost, so no slot moves and no note.
        rows = _contested(5, 3) + _contested(10, 0)
        assert _bare_agent(contested=rows)._build_contested_table_block() == "\n".join(
            [_HEADER] + [f"- **m{i}** — s（S2）" for i in range(5)] + [f"- **q{i}** — a ⇄ b" for i in range(3)]
            + [f"- **m{i}** — s（S2）" for i in range(7)])

    def test_knob_off_is_the_plain_cut(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", False, raising=False)
        assert _bare_agent(contested=_contested(20, 4, unit_scale=(0, 1)))._build_contested_table_block() == (
            _golden(range(15)))
        assert _bare_agent(contested=_contested(20, 4))._build_contested_table_block(max_claims=0) == (
            _golden([0]))

    @pytest.mark.parametrize("bad", [
        {"claim": "bad", "positions": 5},
        {"claim": "bad", "positions": {"bull": "x", "bear": "y"}},
        {"claim": "bad", "positions": [{"stance": "x", "sources": 7}]},
        {"claim": "bad", "origin": "quant_reconcile", "positions": 5},
        {"claim": "bad", "origin": "quant_reconcile", "positions": {"bull": "x", "bear": "y"}},
    ], ids=["int", "dict", "int_sources", "quant_int", "quant_dict"])
    def test_malformed_row_past_the_cap_keeps_the_plain_cut(self, reconcile_knob, bad):
        rows = _contested(16, 0) + [bad]
        assert _bare_agent(contested=rows)._build_contested_table_block() == _golden(range(15))

    def test_malformed_quant_row_past_the_cap_is_skipped(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        rows = _contested(20, 0) + [{"claim": "bad", "origin": "quant_reconcile", "positions": 5}] + _contested(0, 1)
        out = _bare_agent(contested=rows)._build_contested_table_block()
        assert out == _golden(range(14), (0,))

    def test_interleaved_tracks_rank_every_quant_slot_by_priority(self, monkeypatch):
        """Review round 2: a multi-track handoff interleaves the tracks' quant rows with the
        next track's claims (merge_list_dedup). With 5 plain quant rows inside the plain cut
        and a unit-scale error past it, every quant slot is chosen by priority: the unit-scale
        row takes the first quant position, the lowest-priority plain row is the one cut, and
        no model claim gives up its slot."""
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        claim = lambda name: {"claim": name, "positions": [{"stance": "s", "sources": [], "tier": "S2"}]}
        quant = lambda name, why: {"claim": name, "origin": "quant_reconcile", "why_they_differ": why,
                                   "positions": [{"stance": "a", "sources": [], "tier": ""},
                                                 {"stance": "b", "sources": [], "tier": ""}]}
        rows = ([claim(f"m{i}") for i in range(5)] + [quant(f"q{i}", "high/low ratio=1.5") for i in range(5)]
                + [claim(f"m{i}") for i in range(5, 10)] + [quant("u0", _UNIT_SCALE_WHY)])
        out = _bare_agent(contested=rows)._build_contested_table_block()
        model = lambda i: f"- **m{i}** — s（S2）"
        q = lambda name: f"- **{name}** — a ⇄ b"
        assert out == "\n".join([_HEADER] + [model(i) for i in range(5)]
                                 + [q("u0"), q("q0"), q("q1"), q("q2")] + [model(i) for i in range(5, 10)]
                                 + [q("q3"), "（另有 1 条数值对账分歧超出上限未列出）"])


    def test_few_model_claims_leave_more_room_for_quant_rows(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        out = _bare_agent(contested=_contested(3, 20))._build_contested_table_block()
        assert out == _golden(range(3), range(12)) + "\n（另有 8 条数值对账分歧超出上限未列出）"


class TestChronologyBlock:
    def test_empty_when_no_data(self):
        assert _bare_agent()._build_chronology_block() == ""

    def test_ascending_recent_and_dedup(self):
        rows = ([{"date": "2018-05", "event": "old shock"}]
                + [{"date": f"2026-0{i}", "event": f"e{i}"} for i in range(1, 6)]
                + [{"date": "2026-01", "event": "e1"}])  # 重复
        out = _bare_agent(timeline_events=rows)._build_chronology_block(max_events=5)
        lines = [l for l in out.split("\n") if l.startswith("- ")]
        assert len(lines) == 5 and "old shock" not in out  # 取最近 5 条、重复剔除
        assert lines == sorted(lines)  # 升序


class TestKgStructuralNote:
    def test_empty_without_priors(self):
        assert _bare_agent()._kg_structural_note("TSMC", {}) == ""

    def test_alias_max_dedupe_and_rank(self):
        a = _bare_agent(graph_priors={"TSMC": 0.9, "2330.TW": 0.9, "NVIDIA": 0.5})
        note = a._kg_structural_note("TSMC", {"aliases": ["2330.TW"]})
        assert "0.90" in note and "第1" in note

    def test_chokepoint_flag(self):
        a = _bare_agent(graph_priors={"BIS": 0.3},
                        graph_priors_structural={"chokepoints": ["BIS"]})
        assert "结构瓶颈点" in a._kg_structural_note("BIS", {})


class TestSectionTitleInjection:
    def _agent_with_blocks(self):
        a = _bare_agent()
        a._background_block = "BG"
        a._sources_index = ""
        a._forecast_spine_block = ""
        a._signal_pack = ""
        a._contested_table_block = "CONTESTED-BLOCK"
        a._chronology_block = "CHRONO-BLOCK"
        return a

    def test_risk_title_gets_contested(self):
        out = self._agent_with_blocks()._prepend_research_background(
            "PROMPT", section_title="风险与不确定性")
        assert "CONTESTED-BLOCK" in out and "CHRONO-BLOCK" not in out

    def test_background_title_gets_chronology(self):
        out = self._agent_with_blocks()._prepend_research_background(
            "PROMPT", section_title="Background and Timeline")
        assert "CHRONO-BLOCK" in out and "CONTESTED-BLOCK" in out or "CHRONO-BLOCK" in out

    def test_plain_title_unchanged(self):
        out = self._agent_with_blocks()._prepend_research_background(
            "PROMPT", section_title="Scenario Forecasts")
        assert "CONTESTED-BLOCK" not in out and "CHRONO-BLOCK" not in out
        assert out.endswith("PROMPT") and out.startswith("BG")

    def test_no_title_backward_compatible(self):
        out = self._agent_with_blocks()._prepend_research_background("PROMPT")
        assert "CONTESTED-BLOCK" not in out and "CHRONO-BLOCK" not in out


class TestSimleakSkipLine:
    def test_bold_lead_is_prose(self):
        assert ReportAgent._simleak_skip_line("**TSMC**: 48 次动作居首") is False

    def test_bullet_and_heading_skipped(self):
        for s in ("* bullet", "- bullet", "# 标题", "> quote", "| a | b |", "!<img>"):
            assert ReportAgent._simleak_skip_line(s) is True
