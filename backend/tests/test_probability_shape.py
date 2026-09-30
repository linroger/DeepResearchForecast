"""REPORT-11: probability-shape telemetry (quality.probability_shape) — offline.

The pure module (app/services/probability_shape.py) measures the scenario spine (peak,
normalized entropy, TV distance from uniform, pre/post-critique delta) and the binary set
(midband / near-half / extreme shares, decile histogram, recorded moves toward or away
from 0.5). ReportAgent snapshots the uncritiqued spine before the red-team critique, writes
the shape into forecast.json before the final audit (no gate reads it), and the published
ledger commit copies it as objective_signals. FORECAST_PROBABILITY_SHAPE=false restores the
old forecast.json and ledger row. Also: the ``forecast_tools.py shape`` CLI and the DRF-2
forecast-report skill's de-Goodharted §2.1.

Offline: FakeLLMClient-based router, stubbed binary extraction; no network, no real LLM.
"""

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.forecast_tools as tools
from app.config import Config
from app.services import forecast_extractor as fe
from app.services import forecast_ledger as fl
from app.services import ledger_commit as lc
from app.services import probability_shape as ps
from app.services.report_agent import ReportAgent, ReportManager
from tests.conftest import FakeLLMClient

_NAMES = ("Rapid adoption path", "Gradual adoption path", "Other / Status Quo")
_SPINE_P = (0.5, 0.3, 0.2)
_CRITIQUE_P = (0.4, 0.35, 0.25)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
SKILL_MD = Path(__file__).resolve().parents[2] / "drf2" / "skills" / "custom" / "forecast-report" / "SKILL.md"


def _named(probs):
    return [{"name": f"S{i}", "probability": p} for i, p in enumerate(probs)]


def _binary_rows(probs):
    return [{"probability": p} for p in probs]


# ------------------------------------------------------------------ pure module
def test_scenario_stats():
    uniform = ps.probability_shape(_named([0.2] * 5))
    assert uniform["version"] == ps.SHAPE_VERSION == "prob-shape/v1"
    sc = uniform["scenarios"]
    assert (sc["n"], sc["max_probability"], sc["normalized_entropy"], sc["tv_from_uniform"]) == (
        5, 0.2, 1.0, 0.0)

    two = ps.probability_shape(_named([0.6, 0.4]))["scenarios"]
    assert two["max_probability"] == 0.6 and two["tv_from_uniform"] == 0.1
    entropy = -(0.6 * math.log(0.6) + 0.4 * math.log(0.4)) / math.log(2)
    assert two["normalized_entropy"] == round(entropy, 4)
    assert "pre_critique" not in two and "critique_delta" not in two

    critiqued = ps.probability_shape(
        _named(_CRITIQUE_P), pre_critique_scenarios=_named(_SPINE_P))["scenarios"]
    assert critiqued["pre_critique"]["n"] == 3
    assert critiqued["pre_critique"]["max_probability"] == 0.5
    delta = critiqued["critique_delta"]
    assert set(delta) == {"max_probability", "normalized_entropy"}
    assert delta["max_probability"] == -0.1
    assert delta["normalized_entropy"] > 0
    assert delta["normalized_entropy"] == round(
        critiqued["normalized_entropy"] - critiqued["pre_critique"]["normalized_entropy"], 4)

    # n < 2: entropy is undefined; bare numbers are read like rows
    one = ps.probability_shape([1.0])["scenarios"]
    assert (one["n"], one["max_probability"], one["normalized_entropy"], one["tv_from_uniform"]) == (
        1, 1.0, None, 0.0)
    # entropy / TV renormalise (rounding residue); the peak stays the raw published value
    rounded = ps.probability_shape(_named([0.34, 0.33, 0.32]))["scenarios"]
    assert rounded["max_probability"] == 0.34 and 0.99 < rounded["normalized_entropy"] <= 1.0
    # an unreadable pre-critique record keeps the block, with None stats and deltas
    empty_pre = ps.probability_shape(_named([0.7, 0.3]), pre_critique_scenarios=[])["scenarios"]
    assert empty_pre["pre_critique"]["n"] == 0
    assert empty_pre["critique_delta"] == {"max_probability": None, "normalized_entropy": None}


def test_binary_stats():
    b = ps.probability_shape(binaries=_binary_rows([0.5, 0.45, 0.9, 0.1]))["binaries"]
    assert b["n"] == 4
    assert (b["midband_share"], b["near_half_share"], b["extreme_share"]) == (0.5, 0.5, 0.0)
    assert b["decile_hist"] == [0, 1, 0, 0, 1, 1, 0, 0, 0, 1] and sum(b["decile_hist"]) == 4
    assert b["mean_abs_from_half"] == round((0.0 + 0.05 + 0.4 + 0.4) / 4, 4)
    mean = (0.5 + 0.45 + 0.9 + 0.1) / 4
    assert b["stdev"] == round(math.sqrt(sum((p - mean) ** 2 for p in (0.5, 0.45, 0.9, 0.1)) / 4), 4)
    assert b["moves"] == {"toward_half": 0, "away_from_half": 0}

    # bin edges: 0.0 first bin, p == 1.0 last bin, k/10 in bin k despite float noise
    edges = ps.probability_shape(binaries=_binary_rows([0.0, 0.3, 0.7, 1.0, 0.05, 0.95]))["binaries"]
    assert edges["decile_hist"] == [2, 0, 0, 1, 0, 0, 0, 1, 0, 2]
    assert edges["extreme_share"] == round(4 / 6, 4)

    # midband is the scorecard's own 0.40-0.60 band (forecast_extractor._binary_quality)
    probs = [0.4, 0.6, 0.39, 0.61, 0.5]
    assert ps.probability_shape(binaries=_binary_rows(probs))["binaries"]["midband_share"] == (
        fe._binary_quality(_binary_rows(probs), min_count=1)["midband_share"])

    stamped = [
        {"probability": 0.8, "market_influence": {"prior_probability": 0.9,
                                                  "revised_probability": 0.8}},       # toward
        {"probability": 0.2, "market_influence": {"prior_probability": 0.4,
                                                  "revised_probability": 0.2}},       # away
        {"probability": 0.9, "market_influence": {"prior_probability": 0.9,
                                                  "revised_probability": 0.55,
                                                  "probability_restored": True}},     # reverted
        {"probability": 0.3, "pre_reconciliation_probability": 0.1},                  # toward
        {"probability": 0.95, "pre_reconciliation_probability": 0.7},                 # away
        {"probability": 0.7, "pre_reconciliation_probability": 0.3},                  # same distance
        {"probability": 0.6, "pre_reconciliation_probability": "0.2"},                # unreadable
        {"probability": 0.6, "market_influence": "not a stamp"},
    ]
    moves = ps.probability_shape(binaries=stamped)["binaries"]["moves"]
    assert moves == {"toward_half": 2, "away_from_half": 2}


@pytest.mark.parametrize("bad", [
    None, float("nan"), "0.4", True, 7, [], {}, (),
    [None, float("nan"), float("inf"), "0.3", True, False, {"probability": "30%"},
     {"probability": 1.5}, {"probability": -0.1}, {"probability": None}, {"name": "x"},
     object()],
])
def test_invalid_inputs_never_raise_and_give_n0(bad):
    shape = ps.probability_shape(bad, bad, pre_critique_scenarios=bad, policy=bad)
    assert shape["version"] == "prob-shape/v1" and shape["policy"] == {}
    sc, b = shape["scenarios"], shape["binaries"]
    assert sc["n"] == 0 and sc["max_probability"] is None
    assert sc["normalized_entropy"] is None and sc["tv_from_uniform"] is None
    assert b["n"] == 0 and b["decile_hist"] is None and b["moves"] == {
        "toward_half": 0, "away_from_half": 0}
    assert all(b[key] is None for key in ("midband_share", "near_half_share", "extreme_share",
                                          "mean_abs_from_half", "stdev"))
    json.dumps(shape, allow_nan=False)


def test_policy_is_copied_and_shape_is_strict_json():
    policy = {"binary_symmetric_guard": True}
    shape = ps.probability_shape(_named(_SPINE_P), _binary_rows([0.2, 0.8]), policy=policy)
    assert shape["policy"] == policy and shape["policy"] is not policy
    json.dumps(shape, allow_nan=False)


def test_snapshot_and_stamp_only_on_a_successful_critique():
    rows = [{"name": n, "probability": p, "summary": "s"} for n, p in zip(_NAMES, _SPINE_P, strict=True)]
    snap = ps.scenario_snapshot(rows + ["junk"])
    assert snap == [{"name": n, "probability": p} for n, p in zip(_NAMES, _SPINE_P, strict=True)]
    assert ps.scenario_snapshot(None) == []
    # strict JSON: the final audit re-serialises forecast.json with allow_nan=False
    odd = ps.scenario_snapshot([{"name": "A", "probability": float("nan")},
                                {"name": "B", "probability": "30%"}, {"probability": 0.7}])
    assert odd == [{"name": "A", "probability": None}, {"name": "B", "probability": "30%"},
                   {"name": None, "probability": 0.7}]
    json.dumps(odd, allow_nan=False)

    shared = {"quote_provenance": {"ungrounded": 0}}
    failed = {"scenarios": rows, "quality": shared}
    assert ps.stamp_pre_critique(failed, snap) is False and failed["quality"] is shared
    critiqued = {"scenarios": rows, "quality": shared, "critiqued": True}
    assert ps.stamp_pre_critique(critiqued, snap) is True
    assert critiqued["quality"] == {"quote_provenance": {"ungrounded": 0},
                                    "pre_critique_scenarios": snap}
    assert shared == {"quote_provenance": {"ungrounded": 0}}  # the uncritiqued spine is untouched
    assert ps.stamp_pre_critique(None, snap) is False


# ------------------------------------------------------------------ report level
def _scenario_rows(probs):
    return [
        {"name": name, "probability": p, "summary": f"{name} summary",
         "key_drivers": ["driver"],
         "resolution_criteria": f"{name} resolves if the index is above {10 + i}% by 2030"}
        for i, (name, p) in enumerate(zip(_NAMES, probs, strict=True))
    ]


def _spine():
    return {"headline": "Adoption outlook", "horizon": "2030", "confidence": "medium",
            "confidence_rationale": "Evidence is mixed.", "key_uncertainties": ["policy"],
            "scenarios": _scenario_rows(_SPINE_P), "schema_version": 1}


class _RouterLLM(FakeLLMClient):
    """FakeLLMClient whose chat_json reply is chosen by the prompt; every call is recorded."""

    def __init__(self, router):
        super().__init__()
        self._router = router

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier,
                          **kwargs)
        return self._router(messages[-1]["content"])


def _router(critique_reply):
    def route(content):
        if content.startswith(fe._CRITIQUE_INSTRUCTIONS):
            return json.loads(json.dumps(critique_reply))
        return _spine()
    return route


def _agent(llm):
    a = ReportAgent.__new__(ReportAgent)
    defaults = {
        "llm": llm, "graph_id": "g1", "simulation_id": "sim1",
        "simulation_requirement": "Will adoption accelerate?",
        "situation_brief": "", "actors": None, "sources": [], "research_report": "",
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "",
        "_market_pack": "", "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {},
    }
    for key, value in defaults.items():
        setattr(a, key, value)
    return a


def _binaries():
    rows = []
    for i, (p, theme) in enumerate(((0.8, "ai"), (0.45, "policy"), (0.1, "trade")), 1):
        rows.append({"id": f"F{i}", "statement": f"Indicator {i} exceeds {10 * i}% by 2027-12-31.",
                     "probability": p,
                     "resolution_criteria": f"Official index above {10 * i}% on 2027-12-31 (OECD)",
                     "theme": theme, "horizon_year": 2027, "criteria_sharp": True})
    # a market restatement that moved F1 toward 0.5 (0.9 -> 0.8)
    rows[0]["market_influence"] = {"market_id": "m1", "prior_probability": 0.9,
                                   "revised_probability": 0.8}
    return rows


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    for name, value in (("REPORT_FORECAST_SELF_CRITIQUE", True),
                        ("REPORT_CRITIQUE_BEFORE_PROSE", True),
                        ("REPORT_PREMORTEM", False),
                        ("REPORT_SPINE_SELFCONSISTENCY_K", 1),
                        ("FORECAST_EMIT_BINARY", True),
                        ("PREDICTION_MARKETS_ENABLED", False),
                        ("FORECAST_BINARY_THEMES", None),
                        ("FORECAST_SIM_SENSITIVITY", False),
                        ("BINARY_FORECASTS_MIN_COUNT", 10),
                        ("REPORT_PUBLISH_GATE", False),
                        ("REPORT_REPAIR_PASSES", False),
                        ("REPORT_FORECAST_LEDGER", True),
                        ("FORECAST_LEDGER_COMMIT_MODE", "published"),
                        ("FORECAST_PROBABILITY_SHAPE", True),
                        ("FORECAST_BINARY_SYMMETRIC_GUARD", False)):
        monkeypatch.setattr(Config, name, value, raising=False)

    def fake_extract(*args, **kwargs):
        rows = _binaries()
        return {"binary_forecasts": rows,
                "binary_quality": fe._binary_quality(rows, min_count=kwargs["min_count"])}

    def fake_reconcile(forecast, *args, **kwargs):
        # scenario-partition reconciliation moved F2 away from 0.5 (0.45 -> 0.3)
        binary = forecast["binary_forecasts"][1]
        binary["pre_reconciliation_probability"] = binary["probability"]
        binary["probability"] = 0.3
        return {"checked": 1, "stub": True}

    monkeypatch.setattr(fe, "extract_binary_forecasts", fake_extract)
    monkeypatch.setattr(fe, "reconcile_forecast_contract", fake_reconcile)
    return tmp_path


def _read_forecast(tmp_path, report_id):
    with open(os.path.join(str(tmp_path), "reports", report_id, "forecast.json"),
              encoding="utf-8") as handle:
        return json.load(handle)


def _run_report(tmp_path, report_id, critique_reply=None, *, spine_first=True):
    reply = {"scenarios": _scenario_rows(_CRITIQUE_P), "confidence": "low"} if (
        critique_reply is None) else critique_reply
    llm = _RouterLLM(_router(reply))
    (tmp_path / "reports" / report_id).mkdir(parents=True)
    agent = _agent(llm)
    if spine_first:
        agent._derive_and_pin_forecast_spine(report_id)
        assert agent._forecast_spine and agent._forecast_spine.get("scenarios")
    agent._finalize_structured_forecast(report_id, "# T\n\nBody text.")
    return llm, _read_forecast(tmp_path, report_id)


def _commit(report_id, forecast, as_of):
    """commit_report over a sealed forecast (publication stubbed as publishable)."""
    text = json.dumps(forecast, ensure_ascii=False, indent=2, allow_nan=False)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    receipt = lc.commit_report(
        report_id=report_id, report_status="completed", error=None,
        question="Will adoption accelerate?", language="English", actors=None,
        scenario_label="", ledger_context={"as_of_date": as_of},
        publication_status_fn=lambda rid: {"publishable": True, "forecast_sha256": sha,
                                           "markdown_sha256": "m" * 64},
        load_forecast_fn=lambda rid: json.loads(text), now=NOW)
    assert receipt["status"] == "committed", receipt
    (row,) = [r for r in fl.read_ledger() if r.get("report_id") == report_id]
    return row


_GATE_KEYS = ("passed", "hard_passed", "hard_issues", "epistemic_issues", "issues")


def test_finalize_writes_shape_gate_unchanged(report_env, monkeypatch):
    llm, forecast = _run_report(report_env, "r_shape")
    quality = forecast["quality"]
    assert forecast["critiqued"] is True
    assert quality["pre_critique_scenarios"] == [
        {"name": n, "probability": p} for n, p in zip(_NAMES, _SPINE_P, strict=True)]
    assert "forecast_policy" not in quality  # the guard knob is off

    shape = quality["probability_shape"]
    assert shape == ps.probability_shape(
        forecast["scenarios"], forecast["binary_forecasts"],
        pre_critique_scenarios=quality["pre_critique_scenarios"],
        policy={"binary_symmetric_guard": False})
    assert shape["version"] == "prob-shape/v1"
    assert shape["policy"] == {"binary_symmetric_guard": False}
    sc = shape["scenarios"]
    assert sc["n"] == 3 and sc["max_probability"] == max(
        s["probability"] for s in forecast["scenarios"])
    assert sc["pre_critique"]["max_probability"] == 0.5
    assert sc["critique_delta"]["max_probability"] < 0 < sc["critique_delta"]["normalized_entropy"]
    b = shape["binaries"]
    assert b["n"] == 3 and sum(b["decile_hist"]) == 3
    # measured on the reconciled probabilities: F2 moved 0.45 -> 0.3
    assert [x["probability"] for x in forecast["binary_forecasts"]] == [0.8, 0.3, 0.1]
    assert b["moves"] == {"toward_half": 1, "away_from_half": 1}

    # No gate reads the telemetry: identical verdicts with and without the keys, and the
    # gate's quality merge keeps them.
    stripped = json.loads(json.dumps(forecast))
    del stripped["quality"]["probability_shape"], stripped["quality"]["pre_critique_scenarios"]
    with_shape = ReportAgent._apply_publish_gate(json.loads(json.dumps(forecast)))
    without = ReportAgent._apply_publish_gate(stripped)
    assert with_shape["quality"]["epistemic_issues"]  # a non-trivial verdict (3 < 10 binaries)
    for key in _GATE_KEYS:
        assert with_shape["quality"][key] == without["quality"][key], key
    assert with_shape["confidence"] == without["confidence"]
    assert with_shape["quality"]["probability_shape"] == shape

    # the published ledger commit carries the sealed shape as objective_signals
    row = _commit("r_shape", forecast, "2026-09-01")
    assert row["objective_signals"] == {"probability_shape": shape}
    assert fl.is_production_calibration_row(row)

    # Knob off: no snapshot, no shape, no signal; prompts and every other byte unchanged.
    monkeypatch.setattr(Config, "FORECAST_PROBABILITY_SHAPE", False, raising=False)
    llm_off, forecast_off = _run_report(report_env, "r_shape_off")
    assert "probability_shape" not in forecast_off["quality"]
    assert "pre_critique_scenarios" not in forecast_off["quality"]
    on_minus_telemetry = json.loads(json.dumps(forecast))
    del on_minus_telemetry["quality"]["probability_shape"]
    del on_minus_telemetry["quality"]["pre_critique_scenarios"]
    assert on_minus_telemetry == forecast_off
    assert [c["messages"] for c in llm_off.calls] == [c["messages"] for c in llm.calls]
    row_off = _commit("r_shape_off", forecast_off, "2026-09-02")
    assert "objective_signals" not in row_off and "objective_signals_dropped" not in row_off


def test_spine_path_early_forecast_carries_the_snapshot(report_env):
    llm = _RouterLLM(_router({"scenarios": _scenario_rows(_CRITIQUE_P), "confidence": "low"}))
    (report_env / "reports" / "r_early").mkdir(parents=True)
    agent = _agent(llm)
    agent._derive_and_pin_forecast_spine("r_early")
    early = _read_forecast(report_env, "r_early")
    assert early["critiqued"] is True
    assert [row["probability"] for row in early["quality"]["pre_critique_scenarios"]] == list(_SPINE_P)
    assert "probability_shape" not in early["quality"]  # computed only at finalization


@pytest.mark.parametrize("reply", [{}, {"scenarios": []}])
def test_failed_critique_records_no_pre_critique(report_env, reply):
    _llm, forecast = _run_report(report_env, "r_failed", critique_reply=reply)
    assert not forecast.get("critiqued")
    assert "pre_critique_scenarios" not in forecast.get("quality", {})
    sc = forecast["quality"]["probability_shape"]["scenarios"]
    assert "pre_critique" not in sc and "critique_delta" not in sc
    assert sc["max_probability"] == 0.5


def test_post_hoc_critique_records_pre_critique(report_env, monkeypatch):
    """No pre-prose spine: the post-hoc critique in _finalize snapshots the extracted forecast."""
    monkeypatch.setattr(fe, "extract_structured_forecast",
                        lambda *args, **kwargs: _spine())
    _llm, forecast = _run_report(report_env, "r_post_hoc", spine_first=False)
    assert forecast["critiqued"] is True
    assert [row["probability"] for row in forecast["quality"]["pre_critique_scenarios"]] == list(
        _SPINE_P)
    delta = forecast["quality"]["probability_shape"]["scenarios"]["critique_delta"]
    assert delta["max_probability"] < 0


def test_legacy_commit_mode_row_is_unchanged(report_env, monkeypatch):
    """FORECAST_LEDGER_COMMIT_MODE=legacy appends the pre-audit draft via append_forecast;
    REPORT-11 never passes it objective_signals, so the legacy row is the same either way."""
    monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "legacy", raising=False)
    _llm, forecast_on = _run_report(report_env, "r_legacy_on")
    assert "probability_shape" in forecast_on["quality"]
    monkeypatch.setattr(Config, "FORECAST_PROBABILITY_SHAPE", False, raising=False)
    _run_report(report_env, "r_legacy_off")
    rows = {r["report_id"]: r for r in fl.read_ledger()}
    on, off = rows["r_legacy_on"], rows["r_legacy_off"]
    assert on["schema_version"] == 1 and "objective_signals" not in on

    def comparable(row):
        return {k: v for k, v in row.items() if k not in ("report_id", "created_at")}

    assert comparable(on) == comparable(off)


# ------------------------------------------------------------------ CLI + skill
def _cli(capsys, *argv):
    code = tools.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_shape_forecasts_prints_prob_shape(tmp_path, capsys):
    guarded = {"scenarios": _named(_CRITIQUE_P), "binary_forecasts": _binary_rows([0.2, 0.8]),
               "quality": {"forecast_policy": {"binary_symmetric_guard": True},
                           "pre_critique_scenarios": _named(_SPINE_P)}}
    legacy = {"scenarios": _named([0.7, 0.3])}  # older than REPORT-11: policy unknown
    paths = []
    for name, payload in (("guarded.json", guarded), ("legacy.json", legacy)):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(str(path))
    code, out, err = _cli(capsys, "shape", "--forecasts", *paths)
    assert code == 0 and err == ""
    first, second = json.loads(out)
    assert first["file"] == paths[0]
    assert first["probability_shape"]["version"] == "prob-shape/v1"
    assert first["probability_shape"] == ps.probability_shape(
        guarded["scenarios"], guarded["binary_forecasts"],
        pre_critique_scenarios=guarded["quality"]["pre_critique_scenarios"],
        policy={"binary_symmetric_guard": True})
    assert second["probability_shape"]["policy"] == {}
    assert second["probability_shape"]["scenarios"]["max_probability"] == 0.7

    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    code, out, err = _cli(capsys, "shape", "--forecasts", str(bad), paths[1],
                          str(tmp_path / "missing.json"))
    assert code == 1 and "not a forecast object" in err and "missing.json" in err
    assert [r["file"] for r in json.loads(out)] == [paths[1]]


def test_cli_shape_ledger_prints_summary(tmp_path, capsys):
    d = str(tmp_path / "ledger")
    shape = ps.probability_shape(_named(_SPINE_P), policy={"binary_symmetric_guard": False})
    status, _row = fl.commit_published_forecast(
        {"horizon": "2030", "scenarios": _named(_SPINE_P)}, report_id="r1", question="q",
        language="English", as_of_date="2026-09-01", as_of_source="validated",
        publication={"forecast_sha256": "f" * 64}, d=d,
        objective_signals={"probability_shape": shape})
    assert status == "committed"
    code, out, _err = _cli(capsys, "shape", "--ledger-dir", d)
    summary = json.loads(out)
    assert code == 0 and summary["version"] == fl.SHAPE_SUMMARY_VERSION
    (group,) = summary["groups"]
    assert group["binary_symmetric_guard"] is False and group["n"] == 1
    assert group["metrics"]["scenarios.max_probability"] == {"n": 1, "mean": 0.5, "median": 0.5}


def test_skill_no_longer_cues_the_gate():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "will fail the report otherwise" not in text
    assert "Never manufacture extremity" in text
    assert "not targets to aim the probabilities at" in text
    # the checklist no longer demands "no 0.40–0.60 clustering" as a target in itself
    assert "no 0.40–0.60 clustering" not in text
