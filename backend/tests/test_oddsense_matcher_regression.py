"""Retain the original machine-ID, direct-URL and unrelated-topic matcher controls."""
import pytest

from tests.test_bridge_prediction_markets import d


@pytest.mark.parametrize("report, expected", [
    ("The evidence diverges from market 691340, currently 15.45%.", True),
    ("See https://polymarket.com/event/ai-bubble-burst-in-2026 for the live quote.", True),
    ("A celebrity election market has no bearing on semiconductor demand.", False),
], ids=["machine-identity", "direct-url", "unrelated-topic"])
def test_market_report_match_prefers_machine_identity_and_is_conservative(report, expected):
    market = {
        "market_id": "691340", "question": "AI bubble burst in 2026?",
        "implied_yes_prob": 0.1545,
        "url": "https://polymarket.com/event/ai-bubble-burst-in-2026",
    }
    assert d._market_is_cited_in_report(report, market) is expected
