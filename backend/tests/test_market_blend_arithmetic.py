"""REPORT-12: deterministic market-blend arithmetic for the 10pp divergence restatement.

With FORECAST_MARKET_BLEND_ARITHMETIC on, enforce_market_divergence asks the model only
for judgment inputs (a bounded market_weight plus a market-citing rationale, all or
none) and code computes the revised probability (1-w)*p + w*m from DRF's own snapshot
price m.  The formula and its inputs are stamped into market_influence.blend, passed
through the comparison payload and shown in the Market Cross-Check.  With the knob off
(the default) the prompt and the legacy free-probability restatement are byte-identical.

Offline: FakeLLMClient replies only; no network, no real LLM.
"""

import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import config_audit
from app.config import Config
from app.services import forecast_extractor as fe
from app.services.forecast_extractor import (
    build_market_comparison,
    enforce_market_divergence,
    reconcile_forecast_contract,
)
from app.services.report_agent import (
    _mc_influences_from_forecast,
    render_market_comparison_block,
)
from app.utils import prediction_markets
from tests.conftest import FakeLLMClient

REPO_ROOT = Path(__file__).resolve().parents[2]
CITING = "The market implies 60%; I defer partly to the market."
FORMULA = "(1-w)*p + w*m"


@pytest.fixture
def blend_on(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_MARKET_BLEND_ARITHMETIC", True, raising=False)


def _divergent(prob=0.30, implied=0.60, confidence=0.9, fid="F1"):
    """A binary diverging from a high-confidence market by > 10pp, rationale not citing it."""
    return {
        "id": fid, "statement": "X happens by 2027", "probability": prob,
        "adjustment_rationale": "base rate says low",
        "market_anchor": {
            "market_id": "m-1", "question": "Will X happen by 2027?",
            "implied_yes_prob": implied, "price_at_research": implied,
            "divergence": round(prob - implied, 4),
            "url": "https://polymarket.com/event/x", "endDate": "2027-12-31",
            "resolution_equivalence": "near", "match_confidence": confidence,
        },
    }


def _reply(*revisions):
    return FakeLLMClient(json_responses=[{"revisions": list(revisions)}])


def _prompt(fake):
    assert len(fake.calls) == 1
    return fake.calls[0]["messages"][0]["content"]


# ------------------------------------------------------------- code computes the blend
def test_blend_computed_by_code(blend_on):
    b = _divergent(prob=0.30, implied=0.60)
    fake = _reply({"id": "F1", "market_weight": 0.4, "adjustment_rationale": CITING})
    assert enforce_market_divergence([b], fake) == 1
    assert b["probability"] == 0.42                       # (1-0.4)*0.30 + 0.4*0.60
    assert b["market_anchor"]["divergence"] == round(0.42 - 0.60, 4)
    inf = b["market_influence"]
    assert inf["blend"] == {"weight": 0.4, "prior": 0.3, "market": 0.6,
                            "computed": 0.42, "formula": FORMULA}
    assert inf["prior_probability"] == 0.3 and inf["revised_probability"] == 0.42
    assert inf["price_at_revision"] == 0.6 and inf["market_id"] == "m-1"
    assert b["adjustment_rationale"] == (
        CITING + " [blend: (1-0.40)x0.30 + 0.40x0.60 = 0.42]")
    prompt = _prompt(fake)
    assert prompt.startswith(fe._MARKET_BLEND_INSTRUCTIONS.format(weight_max="0.8"))
    assert '"market_weight": 0.0-0.8' in prompt
    assert "the maximum is 0.8" in prompt
    assert "Do NOT output a probability" in prompt
    assert '"probability": 0.02-0.98' not in prompt      # no free probability is requested
    # The comparison payload carries the formula record for the report surface.
    mc = build_market_comparison([b])
    assert mc["influences"][0]["blend"] == inf["blend"]
    assert mc["comparisons"][0]["divergence"] == round(0.42 - 0.60, 4)


def test_blend_toward_lower_market_and_bounds(blend_on):
    b = _divergent(prob=0.80, implied=0.20)
    assert enforce_market_divergence(
        [b], _reply({"id": "F1", "market_weight": 0.8, "adjustment_rationale": CITING})) == 1
    assert b["probability"] == 0.32                       # 0.2*0.80 + 0.8*0.20, max weight
    assert b["adjustment_rationale"].endswith("[blend: (1-0.80)x0.80 + 0.80x0.20 = 0.32]")
    # The [0.02, 0.98] publication bounds still apply to the computed value.
    low = _divergent(prob=0.02, implied=0.0)
    low["market_anchor"]["divergence"] = 0.12             # force candidacy
    assert enforce_market_divergence(
        [low], _reply({"id": "F1", "market_weight": 0.5, "adjustment_rationale": CITING})) == 1
    assert low["probability"] == 0.02                     # 0.01 clamped up, equals p
    assert "market_influence" not in low                  # the probability did not move


@pytest.mark.parametrize("p", [0.05, 0.2, 0.3, 0.47, 0.65, 0.9, 0.98])
@pytest.mark.parametrize("m", [0.0, 0.1234, 0.5, 0.875, 1.0])
@pytest.mark.parametrize("w", [0.05, 0.25, 0.4, 0.8])
def test_every_blend_lies_on_segment_and_is_reproducible(blend_on, p, m, w):
    if abs(p - m) <= 0.10:
        pytest.skip("within the 10pp band: not a revision candidate")
    b = _divergent(prob=p, implied=m)
    assert enforce_market_divergence(
        [b], _reply({"id": "F1", "market_weight": w, "adjustment_rationale": CITING})) == 1
    p2 = b["probability"]
    assert min(p, m) - 1e-9 <= p2 <= max(p, m) + 1e-9     # on the segment p..m
    inf = b.get("market_influence")
    if inf is None:                                       # rounding left p unchanged
        assert p2 == p
        return
    blend = inf["blend"]
    assert blend["weight"] <= Config.FORECAST_MARKET_BLEND_WEIGHT_MAX
    assert blend["market"] == b["market_anchor"]["implied_yes_prob"]
    recomputed = round(min(0.98, max(0.02, (1 - blend["weight"]) * blend["prior"]
                                     + blend["weight"] * blend["market"])), 2)
    assert recomputed == blend["computed"] == p2 == inf["revised_probability"]


# ---------------------------------------------------- all-or-none group and the caps
@pytest.mark.parametrize("revision", [
    {"id": "F1", "market_weight": 0.4, "adjustment_rationale": "base rates dominate"},
    {"id": "F1", "market_weight": 0.4},
    {"id": "F1", "adjustment_rationale": CITING},
    {"id": "F1", "market_weight": None, "adjustment_rationale": CITING},
    {"id": "F1", "market_weight": 0.9, "adjustment_rationale": CITING},
    {"id": "F1", "market_weight": "90%", "adjustment_rationale": CITING},
    {"id": "F1", "market_weight": True, "adjustment_rationale": CITING},
    {"id": "F1", "market_weight": "30-40%", "adjustment_rationale": CITING},
    {"id": "F1", "market_weight": 40, "adjustment_rationale": CITING},
    {"id": "F1", "market_weight": -0.2, "adjustment_rationale": CITING},
    {"id": "F1", "market_weight": "about half", "adjustment_rationale": CITING},
], ids=["rationale-not-citing", "weight-without-rationale", "rationale-without-weight",
        "weight-null", "weight-over-max", "percent-over-max", "weight-bool", "weight-range",
        "weight-plain-gt1", "weight-negative", "weight-text"])
def test_all_or_none_and_caps(blend_on, revision):
    b = _divergent()
    before = copy.deepcopy(b)
    assert enforce_market_divergence([b], _reply(revision)) == 0
    assert b == before                                    # rationale, probability, stamp untouched


def test_percent_weight_accepted(blend_on):
    b = _divergent(prob=0.30, implied=0.60)
    assert enforce_market_divergence(
        [b], _reply({"id": "F1", "market_weight": "40%", "adjustment_rationale": CITING})) == 1
    assert b["probability"] == 0.42
    assert b["market_influence"]["blend"]["weight"] == 0.4


def test_weight_max_knob_bounds_prompt_and_acceptance(blend_on, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_MARKET_BLEND_WEIGHT_MAX", 0.5, raising=False)
    b = _divergent()
    fake = _reply({"id": "F1", "market_weight": 0.6, "adjustment_rationale": CITING})
    assert enforce_market_divergence([b], fake) == 0
    assert "the maximum is 0.5" in _prompt(fake) and b["probability"] == 0.30
    b = _divergent()
    assert enforce_market_divergence(
        [b], _reply({"id": "F1", "market_weight": 0.5, "adjustment_rationale": CITING})) == 1
    assert b["probability"] == 0.45
    # An out-of-range setting is clamped to [0, 1]: a weight never overshoots the market.
    monkeypatch.setattr(Config, "FORECAST_MARKET_BLEND_WEIGHT_MAX", 3.0, raising=False)
    assert fe._market_blend_weight_max() == 1.0
    monkeypatch.setattr(Config, "FORECAST_MARKET_BLEND_WEIGHT_MAX", float("nan"), raising=False)
    assert fe._market_blend_weight_max() == 0.8


def test_one_blend_per_forecast(blend_on):
    """A duplicated revision must not blend twice (cumulative weight would exceed the max)."""
    b = _divergent(prob=0.30, implied=0.60)
    fake = _reply({"id": "F1", "market_weight": 0.8, "adjustment_rationale": CITING},
                  {"id": "F1", "market_weight": 0.8, "adjustment_rationale": CITING})
    assert enforce_market_divergence([b], fake) == 1
    assert b["probability"] == 0.54                       # one 0.8 blend, not two (0.59)
    assert b["market_influence"]["blend"]["prior"] == 0.3


def test_rejected_revision_does_not_block_a_valid_one(blend_on):
    b = _divergent(prob=0.30, implied=0.60)
    fake = _reply({"id": "F1", "market_weight": 0.95, "adjustment_rationale": CITING},
                  {"id": "F1", "market_weight": 0.4, "adjustment_rationale": CITING})
    assert enforce_market_divergence([b], fake) == 1
    assert b["probability"] == 0.42


# ------------------------------------------------------------ w == 0 keeps divergence
def test_zero_weight_keeps_divergence(blend_on):
    b = _divergent(prob=0.30, implied=0.60)
    rationale = "The market implies 60% but underweights the regulatory tail risk."
    fake = _reply({"id": "F1", "market_weight": 0, "adjustment_rationale": rationale})
    assert enforce_market_divergence([b], fake) == 1
    assert b["probability"] == 0.30
    assert b["adjustment_rationale"] == rationale         # no blend clause, rationale only
    assert "market_influence" not in b
    assert b["market_anchor"]["divergence"] == -0.3
    b2 = _divergent(prob=0.30, implied=0.60)
    assert enforce_market_divergence(
        [b2], _reply({"id": "F1", "market_weight": "0%", "adjustment_rationale": rationale})) == 1
    assert b2["probability"] == 0.30 and "market_influence" not in b2


# ----------------------------------------------------------- m is DRF's snapshot price
def test_uses_snapshot_price(blend_on):
    b = _divergent(prob=0.30, implied=0.60)
    fake = _reply({"id": "F1", "market_weight": 0.5, "adjustment_rationale": CITING,
                   "probability": 0.95, "implied_yes_prob": 0.90,
                   "market_implied_yes_prob": 0.90, "market_price": 0.90})
    assert enforce_market_divergence([b], fake) == 1
    assert b["probability"] == 0.45                       # 0.5*0.30 + 0.5*0.60, not 0.95/0.90
    assert b["market_influence"]["blend"]["market"] == 0.6
    assert b["market_anchor"]["implied_yes_prob"] == 0.6
    assert b["adjustment_rationale"].endswith("[blend: (1-0.50)x0.30 + 0.50x0.60 = 0.45]")


def test_candidate_selection_unchanged(blend_on):
    """Low-confidence, within-band and already-explained forecasts never reach the model."""
    low_conf = _divergent(confidence=0.4)
    in_band = _divergent(prob=0.55, implied=0.60)
    explained = _divergent()
    explained["adjustment_rationale"] = "The market implies 60% but misreads the base rate."
    fake = _reply({"id": "F1", "market_weight": 0.8, "adjustment_rationale": CITING})
    for b in (low_conf, in_band, explained):
        before = copy.deepcopy(b)
        assert enforce_market_divergence([b], fake) == 0
        assert b == before
    assert fake.calls == []


def test_unreadable_current_probability_rejects_blend(blend_on):
    b = _divergent()
    b["probability"] = None                               # needs_review binary (REPORT-1)
    b["market_anchor"]["divergence"] = -0.6
    before = copy.deepcopy(b)
    assert enforce_market_divergence(
        [b], _reply({"id": "F1", "market_weight": 0.4, "adjustment_rationale": CITING})) == 0
    assert b == before                                    # nothing invented without p


# --------------------------------------------------------------- show-your-work render
def _blend_forecast():
    b = _divergent(prob=0.30, implied=0.60)
    fe._apply_market_blend(b, b["market_anchor"], 0.4, CITING, weight_max=0.8)
    return b


def test_render_show_your_work():
    b = _blend_forecast()
    # Fallback path: influences derived from the binary's market_influence stamp.
    forecast = {"binary_forecasts": [b]}
    assert _mc_influences_from_forecast(forecast)[0]["blend"]["computed"] == 0.42
    en = render_market_comparison_block(forecast, markets=None, lang="en")
    assert " (blend w=0.40: 0.60·30% + 0.40·60% = 42%)" in en
    zh = render_market_comparison_block(forecast, markets=None, lang="zh")
    assert "（混合 w=0.40：0.60·30% + 0.40·60% = 42%）" in zh
    # Payload path: the same influence line from market_comparison.influences.
    payload = {"binary_forecasts": [b], "market_comparison": build_market_comparison([b])}

    def _influence_line(block):
        return next(ln for ln in block.splitlines() if ln.startswith("- F1"))

    for lang, block in (("en", en), ("zh", zh)):
        assert _influence_line(render_market_comparison_block(payload, None, lang)) == (
            _influence_line(block))
    assert _influence_line(en).endswith(
        "match confidence 0.90 (blend w=0.40: 0.60·30% + 0.40·60% = 42%)")
    assert _influence_line(zh).endswith(
        "匹配置信度 0.90）（混合 w=0.40：0.60·30% + 0.40·60% = 42%）")


def test_render_formula_precedes_anchor_removed_note():
    b = _blend_forecast()
    b["market_influence"].update(anchor_removed=True, probability_restored=True)
    en = render_market_comparison_block({"binary_forecasts": [b]}, None, "en")
    assert "= 42%) — anchor removed in reconciliation; probability restored" in en


def test_render_without_or_with_malformed_blend_is_unchanged():
    b = _blend_forecast()
    plain = copy.deepcopy(b)
    del plain["market_influence"]["blend"]
    reference = render_market_comparison_block({"binary_forecasts": [plain]}, None, "en")
    assert "blend" not in reference
    for bad in ({"weight": "x", "prior": 0.3, "market": 0.6, "computed": 0.42},
                {"weight": 0.4, "prior": 0.3, "market": 0.6},
                {"weight": 1.5, "prior": 0.3, "market": 0.6, "computed": 0.42},
                "0.4"):
            broken = copy.deepcopy(b)
            broken["market_influence"]["blend"] = bad
            assert render_market_comparison_block(
                {"binary_forecasts": [broken]}, None, "en") == reference


# -------------------------------------------- restore path keeps using prior_probability
def test_reconcile_restores_prior_of_blended_revision(blend_on):
    """The restore-on-removed-anchor path is unchanged: a blend moved by an anchor that
    reconciliation removes is rolled back to prior_probability; the blend record stays."""
    b = _divergent(prob=0.30, implied=0.60)
    b["resolution_criteria"] = "X confirmed by 2027-12-31"
    assert enforce_market_divergence(
        [b], _reply({"id": "F1", "market_weight": 0.4, "adjustment_rationale": CITING})) == 1
    forecast = {"scenarios": [], "binary_forecasts": [b]}  # anchor lacks the hash binding
    diag = reconcile_forecast_contract(forecast)
    assert "market_anchor" not in b
    assert b["probability"] == 0.3
    assert b["market_influence"]["probability_restored"] is True
    assert b["market_influence"]["blend"]["computed"] == 0.42
    assert diag["restored_market_influences"] == ["F1"]


# ------------------------------------------------------------ end-to-end extraction
def test_extract_binary_forecasts_blend_end_to_end(blend_on, monkeypatch):
    """Extraction -> high-confidence anchoring -> weight-only restatement -> the payload and
    the rendered Market Cross-Check both carry the code-computed blend."""
    from app.services.forecast_extractor import extract_binary_forecasts
    monkeypatch.setattr(prediction_markets, "market_clock_now",
                        lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    markets = [{"market_id": "mkt-1", "question": "Tariffs > 10%?", "implied_yes_prob": 0.55,
                "url": "https://polymarket.com/event/t", "end_date": "2028-12-31"}]
    fake = FakeLLMClient(json_responses=[
        {"binary_forecasts": [
            {"id": "F1", "statement": "US tariff averages over 10% 2026-2028", "probability": 0.20,
             "resolution_criteria": "USITC > 10% by 2028", "theme": "trade", "horizon_year": 2028,
             "adjustment_rationale": "base rate"},
            {"id": "F2", "statement": "AI capex exceeds $500B in 2027", "probability": 0.80,
             "resolution_criteria": "capex > $500B in 2027", "theme": "ai", "horizon_year": 2027,
             "adjustment_rationale": "trend"},
        ]},
        {"matches": [{"forecast_id": "F1", "market_id": "mkt-1",
                      "resolution_equivalence": "exact", "confidence": 0.9}]},
        {"revisions": [{"id": "F1", "market_weight": 0.5, "probability": 0.9,
                        "adjustment_rationale": "The market implies 55%; I close half the gap."}]},
    ])
    out = extract_binary_forecasts("dossier", fake, min_count=2, language="English",
                                   market_pack="table", markets=markets)
    f1 = next(b for b in out["binary_forecasts"] if b["id"] == "F1")
    assert f1["probability"] == 0.38                      # round(0.5*0.20 + 0.5*0.55, 2)
    assert f1["market_influence"]["blend"] == {"weight": 0.5, "prior": 0.2, "market": 0.55,
                                               "computed": 0.38, "formula": FORMULA}
    mc = out["market_comparison"]
    assert mc["influences"][0]["blend"]["computed"] == 0.38
    block = render_market_comparison_block(out, markets=None, lang="en")
    assert "(blend w=0.50: 0.50·20% + 0.50·55% = 38%)" in block


# ------------------------------------------------------------ knob off: byte-identical
def test_flag_off_identical():
    assert Config.FORECAST_MARKET_BLEND_ARITHMETIC is False
    b = _divergent(prob=0.30, implied=0.60)
    fake = _reply({"id": "F1", "probability": 0.45, "market_weight": 0.1,
                   "adjustment_rationale": CITING})
    assert enforce_market_divergence([b], fake) == 1
    assert _prompt(fake) == (
        fe._MARKET_DIVERGENCE_INSTRUCTIONS + "\n\nWrite all text in English."
        + "\n\n[Divergent forecasts]\n"
        + "[F1] statement: X happens by 2027\n"
        + "    your probability: 0.3; market implied YES: 0.6; "
        + "market question: Will X happen by 2027?\n"
        + "    current rationale: base rate says low")
    expected = _divergent(prob=0.30, implied=0.60)
    expected["probability"] = 0.45                        # legacy: the free probability wins
    expected["adjustment_rationale"] = CITING             # no blend clause
    expected["market_anchor"]["divergence"] = round(0.45 - 0.60, 4)
    expected["market_influence"] = {
        "market_id": "m-1", "market_question": "Will X happen by 2027?",
        "price_at_revision": 0.6, "prior_probability": 0.3, "revised_probability": 0.45,
        "match_confidence": 0.9, "resolution_equivalence": "near",
    }
    assert b == expected                                  # no 'blend' key anywhere
    mc = build_market_comparison([b])
    assert "blend" not in mc["influences"][0]
    assert "blend" not in _mc_influences_from_forecast({"binary_forecasts": [b]})[0]
    assert "blend" not in render_market_comparison_block({"binary_forecasts": [b]}, None, "en")


def test_legacy_instructions_text_untouched():
    """The knob-off prompt prefix is the pre-REPORT-12 constant, byte for byte (sha256 of
    _MARKET_DIVERGENCE_INSTRUCTIONS on feat/finharness-transplants before this change)."""
    assert hashlib.sha256(fe._MARKET_DIVERGENCE_INSTRUCTIONS.encode("utf-8")).hexdigest() == (
        "c381292eafe18346a1e1b65a3a26f95b12811bfe1ffaab11e088116f69a9b79a")
    assert "market_weight" not in fe._MARKET_DIVERGENCE_INSTRUCTIONS


def test_knob_defaults_and_documentation():
    assert Config.FORECAST_MARKET_BLEND_ARITHMETIC is False
    assert Config.FORECAST_MARKET_BLEND_WEIGHT_MAX == 0.8
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "# FORECAST_MARKET_BLEND_ARITHMETIC=false" in example
    assert "# FORECAST_MARKET_BLEND_WEIGHT_MAX=0.8" in example
    # A weight cap above 1 would overshoot the market: the config audit names it.
    knobs = config_audit.extract_knobs(config_audit.CONFIG_SOURCE_PATH)
    issues = config_audit.audit_env({"FORECAST_MARKET_BLEND_WEIGHT_MAX": "1.5"}, knobs)
    assert [i.knob for i in issues] == ["FORECAST_MARKET_BLEND_WEIGHT_MAX"]
    assert config_audit.audit_env({"FORECAST_MARKET_BLEND_WEIGHT_MAX": "0.8",
                                   "FORECAST_MARKET_BLEND_ARITHMETIC": "false"}, knobs) == []
