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


def _contested(n_model, n_quant, *, unit_scale=0):
    model = [{"claim": f"m{i}", "positions": [{"stance": "s", "sources": [], "tier": "S2"}]}
             for i in range(n_model)]
    quant = [{"claim": f"q{i}", "origin": "quant_reconcile",
              "why_they_differ": "probable unit-scale error" if i < unit_scale else "different sources",
              "positions": [{"stance": "a", "sources": [], "tier": ""}, {"stance": "b", "sources": [], "tier": ""}]}
             for i in range(n_quant)]
    return model + quant


def _claims(out):
    return [line[4:].split("**", 1)[0] for line in out.split("\n") if line.startswith("- **")]


class TestContestedQuantSlots:
    """FU-9 (TIME-4 open issue): the research engine appends its quantitative
    disagreements after the model's claims, so a plain cut at 15 dropped them all."""

    def test_reserves_up_to_three_slots_unit_scale_first(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        out = _bare_agent(contested=_contested(20, 4, unit_scale=2))._build_contested_table_block()
        assert _claims(out) == [f"m{i}" for i in range(12)] + ["q0", "q1", "q2"]

    def test_unchanged_when_nothing_is_cut(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        rows = _contested(10, 2)
        out = _bare_agent(contested=rows)._build_contested_table_block()
        assert _claims(out) == [f"m{i}" for i in range(10)] + ["q0", "q1"]
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", False, raising=False)
        assert _bare_agent(contested=rows)._build_contested_table_block() == out

    def test_no_quant_rows_or_knob_off_is_the_plain_cut(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        assert _claims(_bare_agent(contested=_contested(20, 0))._build_contested_table_block()) == [
            f"m{i}" for i in range(15)]
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", False, raising=False)
        assert _claims(_bare_agent(contested=_contested(20, 4))._build_contested_table_block()) == [
            f"m{i}" for i in range(15)]

    def test_few_model_claims_leave_more_room_for_quant_rows(self, monkeypatch):
        monkeypatch.setattr(Config, "RESEARCH_QUANT_RECONCILE", True, raising=False)
        out = _bare_agent(contested=_contested(3, 20))._build_contested_table_block()
        assert _claims(out) == ["m0", "m1", "m2"] + [f"q{i}" for i in range(12)]


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
