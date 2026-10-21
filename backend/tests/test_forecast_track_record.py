"""Only exact, bound ledger metadata is exempt from external-source claim audits."""
from copy import deepcopy

import pytest

from app.services import forecast_track_record as presentation


def _forecast():
    tracks = {kind: {"n_forecasts": 1, "n_resolved": 0, "n_outstanding": 1,
                     "mean_brier": None, "coverage": 0.0}
              for kind in ("scenario", "market_binary", "official_data_binary", "unanchored_binary")}
    tracks["market_binary"].update(n_resolved=1, n_outstanding=0, mean_brier=0.04, coverage=1.0)
    return {"historical_calibration": {"forecast_track_record": {
        "schema_version": 1, "source_digest": "a" * 64, "tracks": tracks}}}


@pytest.mark.parametrize("language", ["English", "Chinese"])
def test_exact_record_is_retained_but_not_counted_as_external_evidence(language):
    forecast = _forecast()
    original = "# Outlook\n\nRevenue is 42 dollars.\n\n## References\n\nSource.\n"
    markdown = presentation.insert(original, forecast, language)
    body, audit = presentation.audit_and_strip(markdown, forecast)
    assert audit["passed"]
    assert "0.0400" in markdown and "0.0400" not in body
    assert "Revenue is 42 dollars." in body
    assert markdown.index(presentation.END) < markdown.index("## References")
    assert presentation.insert(markdown, forecast, language) == markdown


@pytest.mark.parametrize("mutation", ["score", "duplicate", "missing", "unbound"])
def test_tampered_or_unbound_metadata_is_never_exempt(mutation):
    forecast = _forecast()
    markdown = presentation.insert("# Outlook\n", forecast)
    if mutation == "score":
        markdown = markdown.replace("0.0400", "0.0000")
    elif mutation == "duplicate":
        markdown += presentation.render(presentation.snapshot(forecast))
    elif mutation == "missing":
        markdown = markdown.replace(presentation.END, "")
    else:
        forecast = {}
    body, audit = presentation.audit_and_strip(markdown, forecast)
    assert audit["passed"] is False
    assert body == markdown


def test_invalid_denominator_fails_before_rendering():
    forecast = deepcopy(_forecast())
    forecast["historical_calibration"]["forecast_track_record"]["tracks"]["scenario"]["n_forecasts"] = 9
    with pytest.raises(ValueError, match="denominator"):
        presentation.insert("# Outlook\n", forecast)
