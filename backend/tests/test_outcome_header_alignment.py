"""S0.6 — the scenario-share block header is rendered and parsed from one constant.

Before ADR 0003 the renderer wrote ``【推演结果分布 P(outcome)`` while the
extractor's reader still matched ``【预测结果分布 P(outcome)``, so the dormant
legacy_prompt reconciliation could never see the block.
"""
from __future__ import annotations

from app.services import forecast_extractor as fx
from app.services import sim_provenance as sp


def _block(header: str) -> str:
    return (f"【{header}（elicited model projection——模型引出的推演投影，非观察证据；"
            "仅供机制分析，不得据此调整概率）】\n· 突破: 60%\n· 维持现状: 40%\n")


def test_reader_matches_the_rendered_header_and_the_legacy_fixture_wording():
    pat = sp.outcome_shares_header_re()
    assert pat.search(_block(sp.OUTCOME_SHARES_HEADER_ZH))
    assert pat.search(_block(sp.OUTCOME_SHARES_HEADER_LEGACY_ZH))
    assert not pat.search("【议程设置力分层】")
    assert fx._WS_OUTCOME_HEADER_RE.pattern == pat.pattern


def test_taxonomy_row_uses_the_shared_regex():
    rows = {name: block_re for name, block_re, _label_re in fx._SIM_SIGNAL_TAXONOMY}
    assert rows["world-state outcome shares"].pattern == sp.outcome_shares_header_re().pattern


def test_shares_parse_from_the_header_the_report_renders():
    parsed = fx.world_state_outcome_from_signal_pack(_block(sp.OUTCOME_SHARES_HEADER_ZH))
    assert parsed is not None
    shares = parsed["scenario_shares"]
    assert abs(shares["突破"] - 0.6) < 1e-9 and abs(shares["维持现状"] - 0.4) < 1e-9
    legacy = fx.world_state_outcome_from_signal_pack(_block(sp.OUTCOME_SHARES_HEADER_LEGACY_ZH))
    assert legacy is not None and legacy["scenario_shares"] == shares
