"""TIME-5: the pure numeric-coherence guard (app/utils/numeric_guards.py).

Quantity and threshold parsing (EN/ZH scales, currencies, ranges, dates), the
status-quo matrix over comparator x event type x probability side, the
report_ffe1ea6bf50d F13 replay, scale mismatch, binding rules (the drafted
latest_actual field, research quant rows, unit compatibility, ambiguous rows)
and the never-raise contract.  Offline and deterministic: no LLM, no network.
"""

import datetime as dt
import itertools
import json

import pytest

from app.utils import numeric_guards as ng

TODAY = dt.date(2026, 10, 1)


def _q(text, unit=""):
    quantity = ng.parse_quantity(text, unit)
    assert quantity is not None, text
    return quantity


# ── parse_quantity ────────────────────────────────────────────────────────────
def test_parse_quantity_scales_and_currencies():
    one_point_two = _q("$1.2 trillion")
    assert one_point_two == dict(_q("1,200 billion USD"), raw="$1.2 trillion")
    assert (one_point_two["lo"], one_point_two["hi"]) == (1.2e12, 1.2e12)
    assert (one_point_two["unit_class"], one_point_two["currency"]) == ("currency", "USD")
    cny = _q("12万亿元")
    assert (cny["lo"], cny["unit_class"], cny["currency"]) == (1.2e13, "currency", "CNY")
    approx = _q("~$54B")
    assert (approx["lo"], approx["currency"]) == (5.4e10, "USD")
    assert _q("1.5万亿美元")["lo"] == 1.5e12 and _q("1.5万亿美元")["currency"] == "USD"
    assert _q("7500亿美元")["lo"] == 7.5e11
    assert _q("¥500亿元")["currency"] == "CNY" and _q("¥500 billion")["currency"] == "JPY"
    assert _q("HK$3bn")["currency"] == "HKD" and _q("€40 million")["currency"] == "EUR"
    twd = _q("NT$ 100")
    assert (twd["lo"], twd["currency"]) == (100.0, "TWD")


def test_parse_quantity_ranges_classes_and_dates():
    rng = _q("735–760 USD billion")
    assert (rng["lo"], rng["hi"], rng["currency"]) == (7.35e11, 7.6e11, "USD")
    assert (_q("3-5%")["lo"], _q("3-5%")["hi"], _q("3-5%")["unit_class"]) == (3.0, 5.0, "percent")
    assert (_q("120 to 80")["lo"], _q("120 to 80")["hi"]) == (120.0, 80.0)  # inversion kept
    assert (_q("80至120")["lo"], _q("80至120")["hi"]) == (80.0, 120.0)
    bp = _q("250bp")
    assert (bp["lo"], bp["unit_class"], bp["currency"]) == (250.0, "bp", None)
    pp = _q("3.5 pp")
    assert (pp["lo"], pp["unit_class"]) == (3.5, "pp")
    assert _q("2个百分点")["unit_class"] == "pp" and _q("25个基点")["unit_class"] == "bp"
    assert _q("-2.5%")["lo"] == -2.5
    assert _q("500 GW")["unit_class"] == "unknown"
    assert _q("17 million")["unit_class"] == "count"
    for date_text in ("in 2027", "by 2030", "December 2027", "end of 2027", "2027年",
                      "2025-2030", "on 2026-12-31", "COVID-19"):
        assert ng.parse_quantity(date_text) is None, date_text
    # "grows 5% to $10 billion" is two figures, never one inflated range
    assert _q("grows 5% to $10 billion")["lo"] == 5.0
    # nothing scales a percentage; a bare letter before a slash is a unit, not a scale
    assert (_q("3% m/m")["lo"], _q("3% m/m")["unit_class"]) == (3.0, "percent")
    assert _q("500 t/y")["lo"] == 500.0
    assert _q("$5B/yr")["lo"] == 5e9
    assert _q("30日元")["currency"] == "JPY"
    assert ng.parse_quantity("F13 and S3") is None  # identifiers, not quantities


def test_parse_quantity_unit_argument_fills_what_the_text_lacks():
    assert _q("735–760", "USD billion")["lo"] == 7.35e11
    assert _q("735–760", "USD billion")["currency"] == "USD"
    assert _q("0.75T", "USD billion")["lo"] == 7.5e11  # the text's own scale wins
    assert _q("4.1", "%")["unit_class"] == "percent"
    assert _q("420", "GW")["unit_class"] == "unknown"
    assert _q("500", "亿元")["lo"] == 5e10 and _q("500", "亿元")["currency"] == "CNY"


# ── parse_threshold_claim ─────────────────────────────────────────────────────
@pytest.mark.parametrize("statement,comparator,threshold", [
    ("Brent exceeds $100 in 2027", ">", 100.0),
    ("US unemployment rises above 5% in 2027", ">", 5.0),
    ("EV sales top 20 million units in 2027", ">", 2e7),
    ("Unemployment is at least 5% in December 2027", ">=", 5.0),
    ("Fed funds rate falls below 3% by end-2027", "<", 3.0),
    ("GDP growth will not exceed 2% in 2027", "<=", 2.0),
    ("Core inflation is no more than 2.5% in December 2027", "<=", 2.5),
    ("美国数据中心资本开支在2027年底前超过1.5万亿美元", ">", 1.5e12),
    ("中国CPI同比低于 3%", "<", 3.0),
    ("失业率不低于5%", ">=", 5.0),
    ("关税税率不超过20%", "<=", 20.0),
    ("铜价跌破每吨8000美元", "<", 8000.0),
])
def test_threshold_comparators_en_zh(statement, comparator, threshold):
    claim = ng.parse_threshold_claim(statement, "")
    assert claim is not None, statement
    assert (claim["comparator"], claim["threshold"]) == (comparator, threshold)


def test_threshold_event_types_and_between():
    touch = ng.parse_threshold_claim("Brent trades above $100 at any point in 2027", "")
    assert touch["event_type"] == "touch" and touch["comparator"] == ">"
    settle = ng.parse_threshold_claim("Bitcoin closes above $110,000 on 2026-12-31", "")
    assert (settle["event_type"], settle["comparator"], settle["threshold"]) == ("settle", ">", 110000.0)
    assert ng.parse_threshold_claim(
        "US effective tariff rate averages over 10% from 2026-2028", "")["event_type"] == "average"
    assert ng.parse_threshold_claim("Brent is above $100 in 2027", "")["event_type"] == "unknown"
    below = ng.parse_threshold_claim("中国CPI同比低于 3%", "")
    assert (below["comparator"], below["unit_class"]) == ("<", "percent")
    inverted = ng.parse_threshold_claim("The index settles between 120 and 80 at year-end 2027", "")
    assert (inverted["comparator"], inverted["threshold"], inverted["threshold_hi"]) == ("between", 120.0, 80.0)
    zh_between = ng.parse_threshold_claim("股价在80至120之间", "")
    assert (zh_between["comparator"], zh_between["threshold"], zh_between["threshold_hi"]) == (
        "between", 80.0, 120.0)


def test_threshold_clause_selection():
    # two thresholds in the chosen clause -> None (never guess which one resolves)
    assert ng.parse_threshold_claim("Brent exceeds $100 and falls below $60 in 2027", "") is None
    # the statement wins; the criteria are read only when it states no threshold
    claim = ng.parse_threshold_claim(
        "The Fed cuts rates", "Fed funds upper bound at most 3.5% on 2026-12-31. Source: FOMC.")
    assert (claim["comparator"], claim["threshold"], claim["event_type"]) == ("<=", 3.5, "settle")
    assert claim["metric"] == "Fed funds upper bound"
    # year references and rankings are not thresholds
    assert ng.parse_threshold_claim("US tariff revenue exceeds 2025 levels by 2027", "") is None
    assert ng.parse_threshold_claim("Over the next 3 years, EV share rises", "") is None
    assert ng.parse_threshold_claim("The top 3 producers control 60% of supply", "") is None
    assert ng.parse_threshold_claim("A ceasefire is signed", "Reported by Reuters") is None
    # a size of decline is not a level the latest actual can be compared with
    for decline in ("Euro-area GDP contracts by more than 1% in 2027", "Brent falls more than 20% in 2026",
                    "出口同比下降超过10%"):
        assert ng.parse_threshold_claim(decline, "") is None, decline
    assert ng.parse_threshold_claim("Brent falls below $60 in 2026", "")["comparator"] == "<"
    assert ng.parse_threshold_claim("GDP grows by more than 3% in 2027", "")["threshold"] == 3.0


# ── check_binary ──────────────────────────────────────────────────────────────
def _binary(statement, p, *, value=None, unit="USD", as_of="2026-06-30", rationale="", anchor=""):
    row = {"id": "F1", "statement": statement, "probability": p, "resolution_criteria": "",
           "adjustment_rationale": rationale, "base_rate_anchor": anchor}
    if value is not None:
        row["latest_actual"] = {"value": value, "unit": unit, "as_of": as_of, "source_ref": "S2"}
    return row


_MATRIX_PHRASES = {
    (">", "settle"): "Brent closes above $100 on 2027-12-31",
    (">", "unknown"): "Brent is above $100 in 2027",
    (">", "touch"): "Brent trades above $100 at any point in 2027",
    (">", "average"): "Brent averages above $100 in 2027",
    (">=", "settle"): "Brent is at least $100 at year-end 2027",
    (">=", "unknown"): "Brent is at least $100 in 2027",
    (">=", "touch"): "Brent reaches at least $100 at any point in 2027",
    (">=", "average"): "Brent averages at least $100 in 2027",
    ("<", "settle"): "Brent closes below $100 on 2027-12-31",
    ("<", "unknown"): "Brent is below $100 in 2027",
    ("<", "touch"): "Brent trades below $100 at any point in 2027",
    ("<", "average"): "Brent averages below $100 in 2027",
    ("<=", "settle"): "Brent is at most $100 at year-end 2027",
    ("<=", "unknown"): "Brent is at most $100 in 2027",
    ("<=", "touch"): "Brent trades at most $100 at any point in 2027",
    ("<=", "average"): "Brent averages at most $100 in 2027",
}


@pytest.mark.parametrize("key,level,p", list(itertools.product(
    sorted(_MATRIX_PHRASES), ("far_above", "far_below", "near"), (0.2, 0.8))))
def test_status_quo_matrix(key, level, p):
    comparator, event = key
    actual = {"far_above": "140", "far_below": "60", "near": "110"}[level]
    stamp = ng.check_binary(_binary(_MATRIX_PHRASES[key], p, value=actual), today=TODAY)
    assert stamp["claim"]["comparator"] == comparator and stamp["claim"]["event_type"] == event
    assert stamp["latest_actual"]["basis"] == "llm_field"
    greater = comparator in (">", ">=")
    state = None
    if level == "far_above":
        state = "satisfied" if greater else "violated"
    elif level == "far_below":
        state = "violated" if greater else "satisfied"
    if event == "average":
        expected = False
    elif event == "touch":
        expected = state == "satisfied" and p < 0.5
    else:
        expected = (state == "satisfied" and p < 0.5) or (state == "violated" and p > 0.5)
    codes = [f["code"] for f in stamp["findings"]]
    assert codes == (["status_quo_contradiction"] if expected else []), (key, level, p, stamp)
    assert stamp["status"] == ("flagged" if expected else "ok")


def test_status_quo_margin_boundary_and_between_has_no_inference():
    # exactly K(1+m) counts as satisfied; just inside the margin does not
    edge = ng.check_binary(_binary("Brent closes above $100 on 2027-12-31", 0.2, value="125"), today=TODAY)
    assert [f["code"] for f in edge["findings"]] == ["status_quo_contradiction"]
    inside = ng.check_binary(_binary("Brent closes above $100 on 2027-12-31", 0.2, value="124"), today=TODAY)
    assert inside["findings"] == [] and inside["status"] == "ok"
    between = ng.check_binary(
        _binary("Brent settles between $80 and $120 at year-end 2027", 0.8, value="300"), today=TODAY)
    assert between["findings"] == [] and between["status"] == "ok"
    wider = ng.check_binary(
        _binary("Brent closes above $100 on 2027-12-31", 0.2, value="110"), status_quo_margin=0.05,
        today=TODAY)
    assert [f["code"] for f in wider["findings"]] == ["status_quo_contradiction"]


F13 = {
    "id": "F13",
    "statement": "US single-year data-centre capex falls below $1.5 trillion by end-2027",
    "probability": 0.22,
    "resolution_criteria": "Resolves YES if reported US data-centre capex for calendar 2027 is under "
                           "$1.5 trillion per company filings and Dell'Oro.",
    "base_rate_anchor": "Capex has compounded above 30% a year since 2023.",
    "adjustment_rationale": "Hyperscaler guidance points to continued acceleration.",
    "latest_actual": {"value": "735–760", "unit": "USD billion", "as_of": "2026-02-01",
                      "source_ref": "S3"},
}


def test_f13_replay_is_flagged_status_quo_contradiction():
    stamp = ng.check_binary(dict(F13), today=TODAY)
    assert stamp["schema"] == 1 and stamp["status"] == "flagged"
    assert stamp["claim"]["comparator"] == "<" and stamp["claim"]["threshold"] == 1.5e12
    assert stamp["latest_actual"] == {"value": "735–760", "unit": "USD billion", "as_of": "2026-02-01",
                                      "source_ref": "S3", "basis": "llm_field"}
    (finding,) = stamp["findings"]
    assert finding["code"] == "status_quo_contradiction" and finding["severity"] == "excursion"
    assert finding["justified"] is False and "p=0.22" in finding["detail"]
    json.dumps(stamp)  # the stamp lands in forecast.json

    cited = dict(F13, adjustment_rationale="Guidance implies a doubling of 2026 capex [S3].")
    stamp = ng.check_binary(cited, today=TODAY)
    assert stamp["status"] == "ok"
    assert [(f["code"], f["justified"]) for f in stamp["findings"]] == [("status_quo_contradiction", True)]


def test_scale_mismatch_is_a_misparse_no_citation_justifies():
    binary = _binary("Global AI capex exceeds $6,000 trillion by 2030", 0.3, value="4.3",
                     unit="USD trillion", rationale="Scaling laws [S2].")
    stamp = ng.check_binary(binary, today=TODAY)
    assert stamp["status"] == "flagged"
    assert [(f["code"], f["severity"], f["justified"]) for f in stamp["findings"]] == [
        ("scale_mismatch", "misparse", False)]
    # a lower custom ratio catches a 10x slip; the default does not
    ten_x = _binary("Global AI capex exceeds $43 trillion by 2030", 0.3, value="4.3", unit="USD trillion")
    assert ng.check_binary(ten_x, today=TODAY)["findings"] == []
    assert [f["code"] for f in ng.check_binary(ten_x, scale_ratio=5, today=TODAY)["findings"]] == [
        "scale_mismatch"]


def test_inverted_interval_flags_without_binding():
    stamp = ng.check_binary(_binary("The index settles between 120 and 80 at year-end 2027", 0.4),
                            today=TODAY)
    assert stamp["status"] == "flagged" and stamp["latest_actual"] is None
    assert [f["code"] for f in stamp["findings"]] == ["inverted_interval"]
    # two negative bounds are often written by magnitude: not flagged
    negative = ng.check_binary(_binary("GDP growth settles between -1% and -3% in 2027", 0.4), today=TODAY)
    assert negative["claim"]["comparator"] == "between" and negative["findings"] == []
    assert negative["status"] == "unbound"


def test_unit_class_or_currency_mismatch_never_binds():
    rows = [{"metric": "US unemployment rate", "value": "4.1", "unit": "USD billion",
             "as_of_date": "2026-08-01", "value_type": "actual"}]
    percent_claim = _binary("US unemployment rate rises above 5% in 2027", 0.2, value="4.1",
                            unit="USD billion")
    stamp = ng.check_binary(percent_claim, quant_rows=rows, today=TODAY)
    assert stamp["status"] == "unbound" and stamp["latest_actual"] is None
    cny_actual = _binary("China EV subsidies exceed $50 billion in 2027", 0.2, value="3000", unit="亿元")
    assert ng.check_binary(cny_actual, today=TODAY)["status"] == "unbound"
    gw = _binary("US solar additions exceed 500 GW in 2027", 0.2, value="420", unit="GW")
    assert ng.check_binary(gw, today=TODAY)["status"] == "unbound"


def _capex_row(value, *, metric="US data center capex", value_type="actual", as_of="2026-03-31"):
    return {"metric": metric, "value": value, "unit": "USD billion", "as_of_date": as_of,
            "value_type": value_type, "source_ref": "S4"}


def test_quant_row_binding_and_its_guards():
    claim = {k: v for k, v in F13.items() if k != "latest_actual"}
    claim["statement"] = "US data center capex falls below $1.5 trillion by end-2027"
    stamp = ng.check_binary(claim, quant_rows=[_capex_row("760"), _capex_row(
        "40", metric="US data center power demand")], today=TODAY)
    assert stamp["status"] == "flagged"
    assert stamp["latest_actual"] == {"value": "760", "unit": "USD billion", "as_of": "2026-03-31",
                                      "source_ref": "S4", "basis": "quant_row"}
    # two equal-score rows -> ambiguous -> unbound (never pick one silently)
    tied = ng.check_binary(claim, quant_rows=[_capex_row("760"), _capex_row("700", as_of="2025-12-31")],
                           today=TODAY)
    assert tied["status"] == "unbound" and tied["latest_actual"] is None
    # forecasts, typed projections and future-dated rows are not actuals
    for row in (_capex_row("2000", value_type="forecast"), _capex_row("760", as_of="2027-06-30"),
                dict(_capex_row("760"), value_type=None, epistemic_class="projected")):
        assert ng.check_binary(claim, quant_rows=[row], today=TODAY)["status"] == "unbound", row
    missing_type = dict(_capex_row("760"))
    missing_type.pop("value_type")
    assert ng.check_binary(claim, quant_rows=[missing_type], today=TODAY)["latest_actual"]["basis"] == "quant_row"
    # a weak metric match does not bind
    weak = ng.check_binary(claim, quant_rows=[_capex_row("760", metric="Global chip sales")], today=TODAY)
    assert weak["status"] == "unbound"


def test_future_or_unparseable_latest_actual_falls_back():
    future = dict(F13, latest_actual=dict(F13["latest_actual"], as_of="2027-03-01"))
    assert ng.check_binary(future, today=TODAY)["status"] == "unbound"
    garbled = dict(F13, latest_actual={"value": "not stated", "unit": "", "as_of": "", "source_ref": ""})
    stamp = ng.check_binary(garbled, quant_rows=[_capex_row("760", metric="US single-year data-centre capex")],
                            today=TODAY)
    assert stamp["latest_actual"]["basis"] == "quant_row" and stamp["status"] == "flagged"


def test_not_numeric_and_unchecked(monkeypatch):
    assert ng.check_binary(_binary("A ceasefire is signed in 2027", 0.4), today=TODAY)["status"] == "not_numeric"
    assert ng.check_binary("not a binary")["status"] == "unchecked"

    def boom(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(ng, "_bind", boom)
    stamp = ng.check_binary(dict(F13), today=TODAY)
    assert stamp["status"] == "unchecked" and stamp["error"] == "RuntimeError"
    forecast = {"binary_forecasts": [dict(F13), _binary("A ceasefire is signed", 0.4)]}
    summary = ng.stamp_forecast(forecast, today=TODAY)
    assert summary["status"] == "ran" and summary["by_status"] == {"unchecked": 1, "not_numeric": 1}
    assert forecast["binary_forecasts"][0]["numeric_guard"]["status"] == "unchecked"


# ── stamp_forecast / check_scenarios / helpers ─────────────────────────────────
def test_stamp_forecast_summary_and_scenarios():
    scenarios = [{"name": "Band", "resolution_criteria": "Brent settles between $120 and $80 at year-end"},
                 {"name": "Range", "resolution_criteria": "Inflation of 4%–2% through 2027"},
                 {"name": "Fine", "resolution_criteria": "Brent between $80 and $120 over 2025-2030"},
                 {"name": "Negative", "resolution_criteria": "GDP growth of -1% to -3% in 2027"}]
    forecast = {"binary_forecasts": [dict(F13), _binary("A ceasefire is signed", 0.4),
                                     _binary("Brent is above $100 in 2027", 0.8, value="140")],
                "scenarios": scenarios}
    summary = ng.stamp_forecast(forecast, quant_rows=[], mode="shadow", today=TODAY)
    assert summary["mode"] == "shadow" and summary["status"] == "ran"
    assert (summary["n_binaries"], summary["n_numeric"], summary["n_bound"]) == (3, 2, 2)
    assert summary["by_status"] == {"flagged": 1, "not_numeric": 1, "ok": 1}
    assert summary["findings_by_code"] == {"status_quo_contradiction": 1}
    assert [(f["scenario"], f["code"]) for f in summary["scenario_findings"]] == [
        ("Band", "inverted_interval"), ("Range", "inverted_interval")]
    assert (summary["scale_ratio"], summary["status_quo_margin"]) == (300.0, 0.25)
    assert all(b["numeric_guard"]["schema"] == 1 for b in forecast["binary_forecasts"])
    json.dumps(summary)

    empty = {"binary_forecasts": [], "scenarios": scenarios[:1]}
    none_run = ng.stamp_forecast(empty, today=TODAY)
    assert none_run["status"] == "not_run" and none_run["n_binaries"] == 0
    assert len(none_run["scenario_findings"]) == 1
    assert ng.stamp_forecast(None)["status"] == "not_run"
    # unusable knob values fall back to the documented defaults
    odd = ng.stamp_forecast({"binary_forecasts": []}, scale_ratio=0.5, margin=2)
    assert (odd["scale_ratio"], odd["status_quo_margin"]) == (300.0, 0.25)


def test_normalize_mode_and_sanitize_latest_actual():
    assert ng.normalize_mode("shadow") == ("shadow", True)
    assert ng.normalize_mode(" OFF ") == ("off", True)
    for bad in ("enforce", "", None, "true"):
        assert ng.normalize_mode(bad) == ("shadow", False), bad
    assert ng.sanitize_latest_actual({"value": 735.5, "unit": "USD billion", "as_of": "2026-02-01",
                                      "source_ref": "S3", "extra": "dropped"}) == {
        "value": "735.5", "unit": "USD billion", "as_of": "2026-02-01", "source_ref": "S3"}
    capped = ng.sanitize_latest_actual({"value": "9" * 200, "unit": ["x"], "as_of": None})
    assert capped == {"value": "9" * 80, "unit": "", "as_of": "", "source_ref": ""}
    assert ng.sanitize_latest_actual(None) is None
    assert ng.sanitize_latest_actual({"value": "  ", "unit": "USD"}) is None
    assert ng.sanitize_latest_actual("735") is None


def test_public_functions_never_raise():
    assert ng.parse_quantity(None) is None and ng.parse_quantity(object()) is None
    assert ng.parse_threshold_claim(None, None) is None
    assert ng.check_scenarios([None, {"resolution_criteria": None}, 5]) == []
    assert ng.check_scenarios(7) == []
    assert ng.stamp_forecast({"binary_forecasts": [None, "x"]})["status"] == "not_run"


# ── negated events (review round 1) ───────────────────────────────────────────
TARIFF = ("Despite the Feb 2026 SCOTUS IEEPA ruling, the US monthly effective tariff rate never falls "
          "below 8% in any month through December 2027.")  # report_aa776d75c630 / 74dc3a07fdaa, p=0.8
EV_SHARE = "The US EV share of new vehicle sales fails to recover above 10% by the end of 2028."  # b283f119e40e


@pytest.mark.parametrize("statement,comparator,threshold,event", [
    (TARIFF, ">=", 8.0, "touch"),
    (EV_SHARE, "<=", 10.0, "settle"),
    ("Brent won't exceed $100 in 2027", "<=", 100.0, "unknown"),
    ("Brent doesn't fall below $60 in 2027", ">=", 60.0, "unknown"),
    ("Brent is not above $100 in 2027", "<=", 100.0, "unknown"),
    ("Brent fails to exceed $100 in 2027", "<=", 100.0, "unknown"),
    ("CPI cannot fall below 2% in 2027", ">=", 2.0, "unknown"),
    ("Brent will no longer exceed $100 in 2027", "<=", 100.0, "unknown"),
    ("GDP growth will not exceed 2% in 2027", "<=", 2.0, "unknown"),
    ("Brent never exceeds $100 in 2027", "<=", 100.0, "touch"),
    ("Brent does not close the year above $100", "<=", 100.0, "settle"),
    ("Bitcoin does not trade above $150,000 at any point in 2026", "<=", 150000.0, "touch"),
    ("Resolves YES unless the rate exceeds 5%", "<=", 5.0, "unknown"),
    ("出口同比未超过10%", "<=", 10.0, "unknown"),
    ("人民币兑美元汇率不会跌破7.5", ">=", 7.5, "unknown"),
    ("上证指数没有突破3500点", "<=", 3500.0, "unknown"),
    ("寒武纪总市值从未跌破5000亿元", ">=", 5e11, "touch"),
    ("寒武纪总市值未达到1万亿元以上", "<", 1e12, "unknown"),
])
def test_negated_comparators_are_inverted(statement, comparator, threshold, event):
    claim = ng.parse_threshold_claim(statement, "")
    assert claim is not None, statement
    assert (claim["comparator"], claim["threshold"], claim["event_type"], claim["negated"]) == (
        comparator, threshold, event, True), statement


@pytest.mark.parametrize("statement,comparator", [
    ("Whether or not Brent exceeds $100 in 2027", ">"),
    ("It is not clear whether Brent exceeds $100 in 2027", ">"),
    ("Brent does not fail to exceed $100 in 2027", ">"),  # two negators cancel
    ("If tariffs are not repealed, imports exceed $3 trillion in 2027", ">"),
    ("未来一年出口同比超过10%", ">"),
    ("出口不断突破10%", ">"),
    ("关税税率不超过20%", "<="),  # 不超过 is itself the comparator
    ("Core inflation is no more than 2.5% in December 2027", "<="),
])
def test_non_negations_keep_the_comparator(statement, comparator):
    claim = ng.parse_threshold_claim(statement, "")
    assert (claim["comparator"], claim["negated"]) == (comparator, False), statement


def test_negated_real_binaries_are_not_false_flags():
    tariff = dict(_binary(TARIFF, 0.8, value="16.5", unit="%"), id="F5")
    stamp = ng.check_binary(tariff, today=TODAY)
    assert stamp["claim"]["comparator"] == ">=" and stamp["claim"]["negated"] is True
    assert stamp["status"] == "ok" and stamp["findings"] == []
    # a negated touch holds only while the level never crosses: a level still clear of K
    # says nothing at a low p, a level already past K refutes it
    assert ng.check_binary(dict(tariff, probability=0.2), today=TODAY)["findings"] == []
    broken = ng.check_binary(dict(tariff, latest_actual=dict(tariff["latest_actual"], value="5")), today=TODAY)
    assert [f["code"] for f in broken["findings"]] == ["status_quo_contradiction"]
    assert "negated touch event" in broken["findings"][0]["detail"]

    ev = _binary(EV_SHARE, 0.62, value="7", unit="%")
    assert ng.check_binary(ev, today=TODAY)["status"] == "ok"
    low = ng.check_binary(dict(ev, probability=0.3), today=TODAY)
    assert low["status"] == "flagged" and [f["code"] for f in low["findings"]] == ["status_quo_contradiction"]
    # the metric span stops before the negator, so research rows still bind
    rows = [{"metric": "US EV share of new vehicle sales", "value": "7", "unit": "%",
             "as_of_date": "2026-06-30", "value_type": "actual", "source_ref": "S2"}]
    bound = ng.check_binary(_binary(EV_SHARE, 0.62), quant_rows=rows, today=TODAY)
    assert bound["latest_actual"]["basis"] == "quant_row" and bound["status"] == "ok"


# ── ranges: "~", year + amount, trajectories (review round 1) ─────────────────
def test_tilde_before_a_figure_means_approximately():
    assert ng.parse_quantity("2025 ~$400B")["hi"] == 2025.0  # the year alone, no 2025..400B range
    approx = _q("~$700-725B")
    assert (approx["lo"], approx["hi"], approx["currency"]) == (7e11, 7.25e11, "USD")
    assert (_q("700~725")["lo"], _q("700~725")["hi"]) == (700.0, 725.0)
    assert (_q("5%~7%")["lo"], _q("5%~7%")["hi"]) == (5.0, 7.0)
    assert (_q("80～120")["lo"], _q("80～120")["hi"]) == (80.0, 120.0)
    claim = ng.parse_threshold_claim("Big-tech AI capex in 2030 exceeds the 2026 ~$700B level", "")
    assert (claim["comparator"], claim["threshold"], claim["threshold_hi"], claim["currency"]) == (
        ">", 7e11, None, "USD")
    stamp = ng.check_binary(_binary("Big-tech AI capex in 2030 exceeds the 2026 ~$700B level", 0.6), today=TODAY)
    assert stamp["findings"] == [] and stamp["status"] == "unbound"


def test_year_next_to_a_marked_amount_is_not_a_range():
    for text in ("2026 - $700B", "2025-400B", "2026 to $700 billion"):
        assert ng.parse_quantity(text)["hi"] == ng.parse_quantity(text)["lo"], text
    for text in ("2000-2500亿元", "2000~2500亿元"):  # a tight dash rising to an amount stays a range
        tight = _q(text)
        assert (tight["lo"], tight["hi"], tight["currency"]) == (2e11, 2.5e11, "CNY"), text


def test_trajectories_are_not_intervals():
    assert _q("from 40% to 30%")["hi"] == 40.0
    assert _q("从40%至30%")["hi"] == 40.0
    scenarios = [
        {"name": "Capex band", "resolution_criteria": (
            "Hyperscaler capex in 2030 lands within +/-40% of the 2026 ~$700-725B level.")},  # aa776d75c630
        {"name": "EV slide", "resolution_criteria": "EV share falls from 40% to 30% by 2030"},
        {"name": "ZH slide", "resolution_criteria": "电动车渗透率从40%至30%"},
        {"name": "Real inversion", "resolution_criteria": "Inflation of 4%–2% through 2027"},
    ]
    assert [f["scenario"] for f in ng.check_scenarios(scenarios)] == ["Real inversion"]


# ── size of decline vs level (review round 1) ─────────────────────────────────
def test_decline_verbs_do_not_suppress_level_comparators():
    real = ("China's combined share of global mature-node (≥28nm) semiconductor capacity falls between "
            "28% and 38% by 2030.")  # report_c80ca48e67d1
    claim = ng.parse_threshold_claim(real, "")
    assert (claim["comparator"], claim["threshold"], claim["threshold_hi"], claim["unit_class"]) == (
        "between", 28.0, 38.0, "percent")
    for verb in ("sinks", "slumps", "plunges", "tumbles", "falls", "drops"):
        claim = ng.parse_threshold_claim(f"The stock {verb} below $100 in 2027", "")
        assert (claim["comparator"], claim["threshold"]) == ("<", 100.0), verb
    # sizes of decline still yield no pair
    for size in ("Brent falls by between 5% and 10% in 2027", "a drop of under 5% in 2027",
                 "Brent falls 20% or more in 2026", "出口同比下降10%以上", "跌幅低于5%"):
        assert ng.parse_threshold_claim(size, "") is None, size
    # a name glued to letters is no quantity
    assert ng.parse_quantity("28nm") is None and ng.parse_quantity("5G") is None


# ── suffix and inclusive comparators (review round 1) ────────────────────────
@pytest.mark.parametrize("statement,comparator,threshold,event", [
    ("2026年Gartner口径全球数据中心系统IT支出实际达到7500亿美元以上。", ">=", 7.5e11, "unknown"),  # ffe1ea6bf50d
    ("寒武纪（688256.SH）于2026年12月31日前盘中总市值维持在1万亿元以上至少1个交易日。", ">=", 1e12, "touch"),
    ("2026年全球数据中心电力需求容量同比增长达到28%以上。", ">=", 28.0, "unknown"),  # ffe1ea6bf50d
    ("2026年AI芯片液冷渗透率达到或超过50%。", ">=", 50.0, "unknown"),  # ffe1ea6bf50d
    ("2027年失业率在5%及以下", "<=", 5.0, "unknown"),
    ("US unemployment is at or above 5% in 2027", ">=", 5.0, "unknown"),
    ("US unemployment is at or below 4% in 2027", "<=", 4.0, "unknown"),
    ("US unemployment is 5% or more in 2027", ">=", 5.0, "unknown"),
    ("US unemployment is 4% or less in 2027", "<=", 4.0, "unknown"),
    ("Brent stays above $100 for at least 30 consecutive days in 2027", ">", 100.0, "touch"),
])
def test_suffix_and_inclusive_comparators(statement, comparator, threshold, event):
    claim = ng.parse_threshold_claim(statement, "")
    assert claim is not None, statement
    assert (claim["comparator"], claim["threshold"], claim["event_type"]) == (comparator, threshold, event)
    assert claim["text"] == statement.strip()  # read from the statement itself


# ── research-row vocabulary and dating (review round 1) ───────────────────────
def test_quant_row_vocabulary_matches_the_repo():
    claim = {k: v for k, v in F13.items() if k != "latest_actual"}
    claim["statement"] = "US data center capex falls below $1.5 trillion by end-2027"

    def bound(row):
        return ng.check_binary(claim, quant_rows=[row], today=TODAY)["latest_actual"]

    base = _capex_row("760")
    base.pop("value_type")
    base.pop("source_ref")
    assert bound(dict(base, value_kind="forecast", source="Dell'Oro")) is None  # value_kind-only forecast
    legacy = bound(dict(base, value_type="observed", value_kind="actual", source="Dell'Oro"))
    assert legacy["basis"] == "quant_row" and legacy["source_ref"] == "Dell'Oro"  # legacy engine row
    assert bound(dict(base, value_type="observed"))["basis"] == "quant_row"
    assert bound(dict(base, value_type="estimate")) is None
    assert bound(dict(base, epistemic_class="unknown")) is None
    assert bound(dict(base, epistemic_class="reported", value_type="actual"))["basis"] == "quant_row"
    assert bound(dict(base, value_type="actual", period_end="2026-12-31")) is None  # period not over yet


@pytest.mark.parametrize("as_of,binds", [
    ("2026", False), ("2026-Q4", False), ("Dec 2026", False), ("FY2026", False), ("2026年12月", False),
    ("2026-01-10", True), ("2025", True), ("2025-Q4", True), ("", False), ("not stated", False),
])
def test_hindcast_binds_only_periods_that_ended_by_its_as_of(as_of, binds):
    as_of_day = dt.date(2026, 1, 15)
    binary = dict(F13, latest_actual=dict(F13["latest_actual"], as_of=as_of))
    stamp = ng.check_binary(binary, today=as_of_day, require_as_of=True)
    assert (stamp["latest_actual"] is not None) is binds, as_of
    row = _capex_row("760", metric="US single-year data-centre capex", as_of=as_of)
    no_field = {k: v for k, v in F13.items() if k != "latest_actual"}
    summary_forecast = {"binary_forecasts": [no_field]}
    ng.stamp_forecast(summary_forecast, quant_rows=[row], today=as_of_day, require_as_of=True)
    assert (summary_forecast["binary_forecasts"][0]["numeric_guard"]["latest_actual"] is not None) is binds


def test_live_runs_bind_undated_actuals_and_ended_periods():
    for as_of in ("", "2026-Q2", "June 2026"):
        binary = dict(F13, latest_actual=dict(F13["latest_actual"], as_of=as_of))
        assert ng.check_binary(binary, today=TODAY)["latest_actual"] is not None, as_of
    assert ng.check_binary(dict(F13, latest_actual=dict(F13["latest_actual"], as_of="2026-Q4")),
                           today=TODAY)["latest_actual"] is None
