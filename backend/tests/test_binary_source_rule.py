"""REPORT-4 (E): the binary-forecast 'source' line only invites a simulation signal
when one was actually injected.

Under the default SIMULATION_FORECAST_EFFECT=diagnostic_only no signal pack reaches
the binary prompt, yet the legacy 'source' line asked the model to "name the
simulation signal that moved it" -- the fabricated provenance that
_enforce_source_provenance then has to downgrade.  The success metric is
binary_quality.provenance_downgrades == 0 for a compliant reply.
"""

from __future__ import annotations

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.forecast_extractor import extract_binary_forecasts

from tests.conftest import FakeLLMClient

# The pre-REPORT-4 line, spelled out literally (the JSON-example line of the template).
_LEGACY_SOURCE_LINE = (
    '  "source": "provenance of the probability: name the simulation signal that moved it '
    '(e.g. \\"world-state outcome shares\\", \\"coalition map\\") or \\"research-prior\\" '
    'when only research evidence informs it"\n'
)
_NEW_SOURCE_LINE = ('  "source": "research-prior"   '
                    "// no simulation signal is among this run's probability inputs\n")
_MARKET_SUFFIX = ' — or "prediction markets" when a listed market informed the probability'
_SIGNAL_PACK = "【预测结果分布 P(outcome)】\n· 基线：60%\n· 下行：40%"
_MARKET_PACK = "| mkt-1 | Tariffs stay above 10% | implied YES 30% |"


def _reply(*sources):
    probs = (0.2, 0.7, 0.35, 0.8)
    return {"binary_forecasts": [
        {"id": f"F{i}", "statement": f"Statement {i} resolves by 2027", "probability": probs[i - 1],
         "resolution_criteria": f"metric {i} > 1 by 2027 per BLS", "theme": "t",
         "source": src}
        for i, src in enumerate(sources, 1)
    ]}


def _run(*, sources=("research-prior", "research-prior"), **kwargs):
    fake = FakeLLMClient(json_responses=[_reply(*sources) for _ in range(4)])
    out = extract_binary_forecasts("dossier", fake, min_count=len(sources),
                                   language="English", **kwargs)
    return fake.calls[0]["messages"][0]["content"], out


def test_diagnostic_only_prompt_never_asks_to_name_a_simulation_signal():
    prompt, _ = _run(signal_pack=_SIGNAL_PACK)
    assert "name the simulation signal" not in prompt
    assert _NEW_SOURCE_LINE in prompt
    assert _MARKET_SUFFIX not in prompt
    assert "[Simulation quantitative signals]" not in prompt


def test_market_aware_rule_names_the_market_label(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    prompt, _ = _run(market_pack=_MARKET_PACK)
    assert _NEW_SOURCE_LINE.rstrip("\n") + _MARKET_SUFFIX + "\n" in prompt
    assert f'"{fe._SOURCE_MARKET_LABEL}"' in _MARKET_SUFFIX


def test_legacy_prompt_policy_with_signal_pack_keeps_legacy_wording(monkeypatch):
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "legacy_prompt", raising=False)
    prompt, _ = _run(signal_pack=_SIGNAL_PACK)
    assert _LEGACY_SOURCE_LINE in prompt
    assert "[Simulation quantitative signals]" in prompt


def test_knob_off_restores_legacy_prompt_bytes(monkeypatch):
    on, _ = _run(signal_pack=_SIGNAL_PACK)
    monkeypatch.setattr(Config, "REPORT_ABSENCE_MARKERS", False, raising=False)
    off, _ = _run(signal_pack=_SIGNAL_PACK)
    assert _LEGACY_SOURCE_LINE in off and "research-prior\"   //" not in off
    # The source line is the only difference between the two renderings.
    assert off == on.replace(_NEW_SOURCE_LINE, _LEGACY_SOURCE_LINE)
    assert fe._BINARY_FORECAST_INSTRUCTIONS.count("{source_rule}") == 1


def test_legacy_rule_constant_is_the_old_line_verbatim():
    assert "  " + fe._BINARY_SOURCE_RULE_LEGACY + "\n" == _LEGACY_SOURCE_LINE
    assert "  {source_rule}\n" in fe._BINARY_FORECAST_INSTRUCTIONS


def test_compliant_reply_has_zero_provenance_downgrades(monkeypatch):
    _, out = _run(sources=("research-prior", "research-prior"), signal_pack=_SIGNAL_PACK)
    assert out["binary_quality"]["provenance_downgrades"] == 0
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    _, out_m = _run(sources=("research-prior", "prediction markets"), market_pack=_MARKET_PACK)
    assert out_m["binary_quality"]["provenance_downgrades"] == 0


def test_provenance_wall_still_downgrades_an_invented_signal():
    _, out = _run(sources=("world-state outcome shares", "research-prior"),
                  signal_pack=_SIGNAL_PACK)
    assert out["binary_quality"]["provenance_downgrades"] == 1
