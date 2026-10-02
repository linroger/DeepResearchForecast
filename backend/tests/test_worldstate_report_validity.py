"""SIM-1 — report-side consumers honour an explicit non-valid decision-channel verdict.

REPORT_WORLDSTATE_HIDE_INVALID (default on, fail-closed): when
world_state_trajectory.json carries a top-level ``validity`` other than ``valid``,

- ReportAgent._world_state_block keeps only the header, the ⚠️ verdict line, the
  verdict reasons, a hidden-results notice and the closing note — no share line
  and no calendar waypoint, so the body has no number to cite;
- ReportAgent._scenario_diff_structured returns None (no fork comparison table);
- ReportVisualizer.build_worldstate_area(_html) returns None with the skip note
  ``trajectory_not_valid``;
- PipelineOrchestrator._log_decision_channel_outcome records the verdict in
  ``state.options['decision_channel_summary']`` and only warns.

Valid trajectories and legacy trajectories without ``validity`` render byte-
identically to the pre-SIM-1 output. Offline: tmp sim dirs, no LLM, no network.
"""

import copy
import json
import os
import re

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.services import report_agent as ra
from app.services import report_visualizer as rv
from app.services.forecast_extractor import world_state_outcome_from_signal_pack
from app.services.report_agent import ReportAgent
from app.services.report_visualizer import ReportVisualizer

_SHARE_LINE = re.compile(r"^· .*%$", re.M)

_HEADER = ("【推演结果分布 P(outcome)（elicited model projection——模型引出的推演投影，"
           "非观察证据；仅供机制分析，不得据此调整概率）】")
_NOTE = "注：这是结构化情景分析先验，不是观察事实；正文结论必须以研究来源和现实指标校验。"
_HIDDEN = "（有效性未达标：已隐藏结果份额与演化航点——正文不得引用本块任何数字或趋势）"

# Pre-SIM-1 rendering of _LEGACY_V3 (captured from the unmodified _world_state_block).
_LEGACY_V3_GOLDEN = "\n".join([
    _HEADER,
    "· A: 62%",
    "· B: 38%",
    "演化航点（按日历时段）：",
    "截至 2026-07-11: A 60% / B 40%",
    "截至 2026-09-30: A 61% / B 39%",
    "截至 2026-12-31: A 62% / B 38%",
    "于 2026-Q4 前趋稳",
    _NOTE,
])

_LEGACY_V3 = {
    "outcome": {"shares": {"A": 0.62, "B": 0.38}, "leader": "A", "leader_share": 0.62},
    "trajectory": [
        {"round": 0, "shares": {"A": 0.6, "B": 0.4}, "as_of": "2026-07-11"},
        {"round": 1, "shares": {"A": 0.61, "B": 0.39}, "period_start": "2026-07-12",
         "period_end": "2026-09-30", "label": "2026-Q3", "as_of": "2026-09-30"},
        {"round": 2, "shares": {"A": 0.62, "B": 0.38}, "period_start": "2026-10-01",
         "period_end": "2026-12-31", "label": "2026-Q4", "as_of": "2026-12-31"},
    ],
    "converged_at": 2,
    "n_rounds": 2,
    "scenarios": ["A", "B"],
    "schema_version": 3,
    "mode": "calendar",
    "horizon_date": "2027-03-31",
}


def _traj(validity=None, reasons=None, **extra):
    doc = copy.deepcopy(_LEGACY_V3)
    if validity is not None:
        doc["validity"] = validity
        doc["forecast_effect"] = "diagnostic_only" if validity == "valid" else "no_update"
        doc["epistemic_status"] = "elicited_model_projection"
    if reasons is not None:
        doc["validity_reasons"] = reasons
    doc.update(extra)
    return doc


def _write(root, sim_id, doc):
    d = os.path.join(str(root), sim_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "world_state_trajectory.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def _signal_pack_outcome(block):
    """Run the signal-pack parser on ``block`` exactly as rendered.

    Since SIM-3 forecast_extractor._WS_OUTCOME_HEADER_RE recognises the renderer's
    「【推演结果分布」 header, and the parser fails closed on an explicit non-valid
    「⚠️ 有效性裁定」 line, the result depends on the share lines and that verdict line.
    """
    return world_state_outcome_from_signal_pack(block)


def _agent(sim_id, base_id=None):
    agent = ReportAgent.__new__(ReportAgent)
    agent.simulation_id = sim_id
    agent.base_simulation_id = base_id
    agent.scenario_label = "fork"
    return agent


class _RecordingLogger:
    """Stand-in for a non-propagating ``mirofish.*`` logger (caplog misses them)."""

    def __init__(self):
        self.records = []

    def _log(self, level, msg, *args, **_kwargs):
        self.records.append((level, msg % args if args else msg))

    def info(self, msg, *args, **kwargs):
        self._log("info", msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log("warning", msg, *args, **kwargs)

    def of(self, level):
        return [text for lvl, text in self.records if lvl == level]


@pytest.fixture
def sim_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", True, raising=False)
    return tmp_path


def test_knob_defaults_on():
    import app.config as cfgmod
    with open(cfgmod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert ("REPORT_WORLDSTATE_HIDE_INVALID = os.environ.get(\n"
            "        'REPORT_WORLDSTATE_HIDE_INVALID', 'true').strip().lower() == 'true'") in src
    env_example = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(cfgmod.__file__)))), ".env.example")
    with open(env_example, encoding="utf-8") as f:
        assert "# REPORT_WORLDSTATE_HIDE_INVALID=true" in f.read()


# ------------------------------------------------------------ _world_state_block
def test_inconclusive_block_hides_shares_and_waypoints(sim_root):
    _write(sim_root, "sim_x", _traj("inconclusive", ["failed_rounds", "low_valid_coverage"]))
    block = _agent("sim_x")._world_state_block()
    assert "⚠️ 有效性裁定：inconclusive" in block
    assert "裁定原因：failed_rounds、low_valid_coverage" in block
    assert not _SHARE_LINE.search(block)
    # No waypoint section. The mandated hidden-results notice itself names "演化航点",
    # so the waypoint heading and its dated rows are what must be absent.
    assert "演化航点（按日历时段）" not in block and "截至" not in block
    assert "趋稳" not in block and "%" not in block
    lines = block.split("\n")
    assert lines[0] == _HEADER and lines[1].startswith("⚠️ 有效性裁定：inconclusive")
    assert lines[-2:] == [_HIDDEN, _NOTE]
    assert len(lines) == 5
    # fail-closed downstream: the parser recognises the header yet the block yields no
    # sim outcome: no share line is left and the verdict line alone already blocks the
    # parse (the knob-off test below is the pair)
    assert _signal_pack_outcome(block) is None
    assert _signal_pack_outcome("\n".join(lines[:1] + lines[2:])) is None


def test_invalid_block_without_reasons_omits_reason_line(sim_root):
    _write(sim_root, "sim_x", _traj("invalid"))
    block = _agent("sim_x")._world_state_block()
    assert "⚠️ 有效性裁定：invalid" in block
    assert "裁定原因" not in block
    assert block.split("\n")[-2:] == [_HIDDEN, _NOTE]
    assert not _SHARE_LINE.search(block)


def test_legacy_trajectory_without_validity_is_byte_identical(sim_root, monkeypatch):
    _write(sim_root, "sim_x", _traj())
    assert _agent("sim_x")._world_state_block() == _LEGACY_V3_GOLDEN
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", False, raising=False)
    assert _agent("sim_x")._world_state_block() == _LEGACY_V3_GOLDEN


def test_valid_trajectory_renders_identically_with_knob_on_and_off(sim_root, monkeypatch):
    _write(sim_root, "sim_x", _traj("valid", []))
    on = _agent("sim_x")._world_state_block()
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", False, raising=False)
    off = _agent("sim_x")._world_state_block()
    assert on == off == _LEGACY_V3_GOLDEN


def test_knob_off_inconclusive_still_renders_shares(sim_root, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", False, raising=False)
    _write(sim_root, "sim_x", _traj("inconclusive", ["low_valid_coverage"]))
    block = _agent("sim_x")._world_state_block()
    lines = block.split("\n")
    assert lines[1].startswith("⚠️ 有效性裁定：inconclusive")
    # pre-SIM-1 behaviour: the golden rendering plus the ⚠️ line, nothing else
    assert "\n".join(lines[:1] + lines[2:]) == _LEGACY_V3_GOLDEN
    assert "· A: 62%" in lines and "裁定原因" not in block
    assert "演化航点（按日历时段）：" in lines
    # regression pair for the fail-closed parser check: the block still renders its
    # shares, yet the explicit non-valid verdict keeps them out of the parse; the same
    # block without the verdict line parses, so the None comes from the verdict check
    assert _signal_pack_outcome(block) is None
    parsed = _signal_pack_outcome("\n".join(lines[:1] + lines[2:]))
    assert parsed is not None
    assert parsed["scenario_shares"] == {"A": 0.62, "B": 0.38}


_WARN_TAIL = "，本分布不可用作任何依据；forecast_effect=no_update）"


@pytest.mark.parametrize("hide", [True, False])
def test_fallback_demotion_names_roster_coverage_not_failed_rounds(sim_root, monkeypatch,
                                                                   hide):
    """SIM-2: a fallback_share_exceeded demotion can have every round committed, so the
    warning names roster coverage (the only cause shown when the reasons line is hidden
    with REPORT_WORLDSTATE_HIDE_INVALID=false)."""
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", hide, raising=False)
    _write(sim_root, "sim_x", _traj("inconclusive", ["fallback_share_exceeded"]))
    lines = _agent("sim_x")._world_state_block().split("\n")
    assert lines[1] == ("⚠️ 有效性裁定：inconclusive（决策通道名册覆盖不足："
                        "过多名册席位无有效承诺或弃权" + _WARN_TAIL)
    assert "失败/沉默轮" not in "\n".join(lines)


def test_other_non_valid_reasons_keep_failed_or_silent_wording(sim_root):
    _write(sim_root, "sim_x", _traj("inconclusive", ["failed_rounds", "low_valid_coverage"]))
    lines = _agent("sim_x")._world_state_block().split("\n")
    assert lines[1] == "⚠️ 有效性裁定：inconclusive（决策通道存在失败/沉默轮" + _WARN_TAIL
    _write(sim_root, "sim_x", _traj("invalid"))
    lines = _agent("sim_x")._world_state_block().split("\n")
    assert lines[1] == "⚠️ 有效性裁定：invalid（决策通道存在失败/沉默轮" + _WARN_TAIL


# ----------------------------------------------------- _scenario_diff_structured
def test_scenario_diff_none_when_scenario_trajectory_invalid(sim_root, monkeypatch):
    rec = _RecordingLogger()
    monkeypatch.setattr(ra, "logger", rec)
    _write(sim_root, "sim_base", _traj("valid", []))
    _write(sim_root, "sim_fork", _traj("invalid", ["no_valid_rounds"]))
    assert _agent("sim_fork", "sim_base")._scenario_diff_structured() is None
    # the suppression is traceable (unlike a missing trajectory, which logs nothing)
    assert rec.of("info") == [
        "情景对比表跳过：sim_fork 轨迹有效性裁定=invalid（REPORT_WORLDSTATE_HIDE_INVALID）"]
    rec.records.clear()
    assert _agent("sim_missing", "sim_base")._scenario_diff_structured() is None
    assert rec.records == []


def test_scenario_diff_none_when_baseline_trajectory_inconclusive(sim_root, monkeypatch):
    rec = _RecordingLogger()
    monkeypatch.setattr(ra, "logger", rec)
    _write(sim_root, "sim_base", _traj("inconclusive", ["failed_rounds"]))
    _write(sim_root, "sim_fork", _traj("valid", []))
    assert _agent("sim_fork", "sim_base")._scenario_diff_structured() is None
    assert rec.of("info") == [
        "情景对比表跳过：sim_base 轨迹有效性裁定=inconclusive（REPORT_WORLDSTATE_HIDE_INVALID）"]


def test_scenario_diff_dict_when_both_valid_or_legacy(sim_root):
    fork = _traj("valid", [])
    fork["outcome"]["shares"] = {"A": 0.5, "B": 0.5}
    _write(sim_root, "sim_base", _traj("valid", []))
    _write(sim_root, "sim_fork", fork)
    diff = _agent("sim_fork", "sim_base")._scenario_diff_structured()
    assert isinstance(diff, dict)
    assert [d["name"] for d in diff["dimensions"]] == ["A", "B"]
    assert diff["dimensions"][0]["delta"] == "-12.0 pp"
    # legacy trajectories (no validity key) keep the old comparison
    legacy_fork = _traj()
    legacy_fork["outcome"]["shares"] = {"A": 0.5, "B": 0.5}
    _write(sim_root, "sim_base", _traj())
    _write(sim_root, "sim_fork", legacy_fork)
    assert _agent("sim_fork", "sim_base")._scenario_diff_structured() == diff


def test_scenario_diff_knob_off_keeps_legacy_comparison(sim_root, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", False, raising=False)
    _write(sim_root, "sim_base", _traj("valid", []))
    _write(sim_root, "sim_fork", _traj("invalid", ["no_valid_rounds"]))
    diff = _agent("sim_fork", "sim_base")._scenario_diff_structured()
    assert isinstance(diff, dict) and diff["dimensions"]


# ----------------------------------------------------------------- visualizer
@pytest.fixture
def viz(monkeypatch):
    monkeypatch.setattr(ReportVisualizer, "_png_export_ok", lambda self: False)
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", True, raising=False)
    return ReportVisualizer()


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_static_worldstate_chart_skipped_for_non_valid(viz, tmp_path, monkeypatch):
    charts = str(tmp_path / "charts")
    assert viz.build_worldstate_area(_traj("invalid", ["no_valid_rounds"]), charts) is None
    assert viz._skip_notes["worldstate_trajectory"] == {
        "reason": "trajectory_not_valid", "validity": "invalid"}
    viz._skip_notes.clear()
    rel = viz.build_worldstate_area(_traj("valid", []), charts)
    assert rel and rel.endswith(".png") and (tmp_path / rel).is_file()
    assert "worldstate_trajectory" not in viz._skip_notes
    assert viz.build_worldstate_area(_traj(), charts)  # legacy: still builds
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", False, raising=False)
    assert viz.build_worldstate_area(_traj("invalid"), charts)  # knob off: legacy chart


@pytest.mark.skipif(not rv.PLOTLY_AVAILABLE, reason="plotly not installed")
def test_interactive_worldstate_chart_skipped_for_non_valid(viz, tmp_path, monkeypatch):
    charts = str(tmp_path / "charts")
    assert viz.build_worldstate_area_html(
        _traj("inconclusive", ["low_valid_coverage"]), charts) is None
    assert viz._skip_notes["worldstate_trajectory"] == {
        "reason": "trajectory_not_valid", "validity": "inconclusive"}
    viz._skip_notes.clear()
    rel = viz.build_worldstate_area_html(_traj("valid", []), charts)
    assert rel and rel.endswith(".html") and (tmp_path / rel).is_file()
    assert "worldstate_trajectory" not in viz._skip_notes
    assert viz.build_worldstate_area_html(_traj(), charts)  # legacy: still builds
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", False, raising=False)
    assert viz.build_worldstate_area_html(_traj("inconclusive"), charts)


@pytest.mark.skipif(not (rv.PLOTLY_AVAILABLE and rv.MATPLOTLIB_AVAILABLE),
                    reason="plotly/matplotlib not installed")
def test_build_all_records_skip_and_mounts_no_fallback(viz, tmp_path):
    items = viz.build_all("sim1-report", str(tmp_path),
                          {"world_state_trajectory": _traj("invalid", ["no_valid_rounds"])})
    assert "worldstate_trajectory" not in {it["id"] for it in items}
    with open(tmp_path / "viz_manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    ws_skips = [s for s in manifest["skipped"] if s["builder"] == "worldstate_trajectory"]
    # Recorded once: the matplotlib fallback re-sets the note but must not duplicate it.
    assert ws_skips == [{"builder": "worldstate_trajectory", "reason": "trajectory_not_valid",
                         "validity": "invalid"}]
    assert "worldstate_trajectory" not in viz._skip_notes
    assert not (tmp_path / "charts" / "worldstate_trajectory.png").exists()

    items = viz.build_all("sim1-report", str(tmp_path / "valid"),
                          {"world_state_trajectory": _traj("valid", [])})
    assert "worldstate_trajectory" in {it["id"] for it in items}


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_build_all_matplotlib_only_host_records_skip_reason(viz, tmp_path, monkeypatch):
    """Without plotly _attempt never calls the builder; the matplotlib fallback's skip
    note must still reach viz_manifest.json, and a valid trajectory still gets its PNG."""
    monkeypatch.setattr(ReportVisualizer, "_interactive_ok", lambda self: False)
    items = viz.build_all("sim1-report", str(tmp_path),
                          {"world_state_trajectory": _traj("inconclusive",
                                                           ["low_valid_coverage"])})
    assert "worldstate_trajectory" not in {it["id"] for it in items}
    with open(tmp_path / "viz_manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    ws_skips = [s for s in manifest["skipped"] if s["builder"] == "worldstate_trajectory"]
    assert ws_skips == [
        {"builder": "worldstate_trajectory", "reason": "plotly_unavailable_or_disabled"},
        {"builder": "worldstate_trajectory", "reason": "trajectory_not_valid",
         "validity": "inconclusive"},
    ]
    assert "worldstate_trajectory" not in viz._skip_notes
    assert not (tmp_path / "charts" / "worldstate_trajectory.png").exists()

    valid_dir = tmp_path / "valid"
    items = viz.build_all("sim1-report", str(valid_dir),
                          {"world_state_trajectory": _traj("valid", [])})
    ws_items = [it for it in items if it["id"] == "worldstate_trajectory"]
    assert len(ws_items) == 1 and ws_items[0]["type"] == "png"
    with open(valid_dir / "viz_manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    assert [s for s in manifest["skipped"] if s["builder"] == "worldstate_trajectory"] == [
        {"builder": "worldstate_trajectory", "reason": "plotly_unavailable_or_disabled"}]


# ------------------------------------------------ _log_decision_channel_outcome
def _log_outcome(sim_root, monkeypatch, doc):
    sim = sim_root / "sim_log"
    sim.mkdir(exist_ok=True)
    (sim / "simulation_config.json").write_text(
        json.dumps({"world_state_seed": {"scenarios": ["A", "B"]}}), encoding="utf-8")
    _write(sim_root, "sim_log", doc)
    saved = []
    monkeypatch.setattr(po.PipelineManager, "save",
                        classmethod(lambda cls, state: saved.append(state)))
    rec = _RecordingLogger()
    monkeypatch.setattr(po, "logger", rec)
    state = po.PipelineState(pipeline_id="pipe_sim1", prompt="q")
    before = set(state.options)
    orch = po.PipelineOrchestrator.__new__(po.PipelineOrchestrator)
    orch._log_decision_channel_outcome(state, "sim_log")
    assert saved == [state]
    # observation only: the summary is the one option written (no run-health change)
    assert set(state.options) - before == {"decision_channel_summary"}
    return state.options["decision_channel_summary"], rec


def test_log_outcome_records_non_valid_verdict_and_warns(sim_root, monkeypatch):
    summary, rec = _log_outcome(
        sim_root, monkeypatch, _traj("inconclusive", ["low_valid_coverage"]))
    assert summary["validity"] == "inconclusive"
    assert summary["validity_reasons"] == ["low_valid_coverage"]
    assert summary["forecast_effect"] == "no_update"
    assert summary["trajectory_produced"] is True and summary["leader"] == "A"
    warnings = rec.of("warning")
    assert len(warnings) == 1 and "有效性裁定=inconclusive" in warnings[0]
    assert "low_valid_coverage" in warnings[0]


def test_log_outcome_valid_and_legacy_do_not_warn(sim_root, monkeypatch):
    summary, rec = _log_outcome(sim_root, monkeypatch, _traj("valid", []))
    assert (summary["validity"], summary["validity_reasons"],
            summary["forecast_effect"]) == ("valid", [], "diagnostic_only")
    assert rec.of("warning") == []

    summary, rec = _log_outcome(sim_root, monkeypatch, _traj())
    assert (summary["validity"], summary["validity_reasons"],
            summary["forecast_effect"]) == (None, None, None)
    assert rec.of("warning") == []
