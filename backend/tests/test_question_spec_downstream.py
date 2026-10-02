"""RESEARCH-12: downstream consumers of the research question spec (drf.question_spec/v1).

RESEARCH-11's v3 engine mirrors the normalized spec into actors.json ``question_spec``.
QUESTION_SPEC_DOWNSTREAM (default on) lets a valid one (schema, status ok/partial,
spec_sha256 recomputed with the bridge's canonical JSON profile) feed:

* the simulation calendar's horizon ladder, below every deterministic prompt date and
  above the LLM fallback (which it skips): temporal_config.horizon_source 'question_spec';
* PipelineOrchestrator._infer_horizon_date's fallback;
* the spine prompt, as a block first in the research inputs (EVAL-11's spine_kwargs);
* the report's resolution section (operational definitions and every assumption);
* forecast.json ``question_spec`` (final write only; the publish gate is unchanged).

A spec whose deadline is not the run's horizon (an explicit prompt date won the
simulation ladder, or the day is outside the as_of window) never reaches the spine;
the disclosure marks its deadline as not applied and forecast.json records
``horizon_applied: false``.

Without a spec, with a spec that fails its checks, or with the flag off, every consumer
is byte-identical.  Offline: FakeLLMClient-based router, a bare config generator whose
LLM calls are scripted, and the offline prepare harness of test_actor_context_runtime.
"""

from __future__ import annotations

import copy
import inspect
import json
import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app import config as config_module
from app.config import Config
from app.services import forecast_extractor as fe
from app.services import forecast_ledger
from app.services import pipeline_orchestrator as po
from app.services import question_spec as qs
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.report_agent import ReportAgent, ReportManager
from app.services.simulation_config_generator import (
    AgentActivityConfig,
    SimulationConfigGenerator,
    SimulationParameters,
)
from app.services.simulation_manager import SimulationManager
from app.services.zep_entity_reader import FilteredEntities
from app.utils import sim_timeline
from app.utils.actors import forecast_inputs_block
from app.utils.canonical_json import canonical_json_sha256
from tests.conftest import FakeLLMClient

import test_actor_context_runtime as acr

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE = os.path.join(os.path.dirname(_BACKEND), "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import linear_research as lr  # noqa: E402

GOLDEN_PATH = os.path.join(_BACKEND, "tests", "fixtures", "question_spec_golden.json")
with open(GOLDEN_PATH, encoding="utf-8") as _fh:
    GOLDEN = json.load(_fh)
GOLDEN_SPEC = GOLDEN["spec"]
# Pinned literally: a change to either side's canonical JSON profile, to the normalizer or
# to the fixture breaks this constant, not only the equality between the two sides.
GOLDEN_SHA = "c70438fd44c254ce0c9400f051ade21629470bd6324f750fdc21749aa4642abe"
SPEC_DAY = "2027-12-31"

AS_OF = "2026-10-01"
QUESTION = "Who will lead the global data-centre build-out?"      # names no date
SPINE_BLOCK = "\n".join([
    qs.SPINE_BLOCK_HEADER,
    "结果定义：Global installed data-centre IT capacity is at least 250 GW (≥ 250 GW) on 31 December 2027.",
    "判定来源：IEA Energy and AI report（官方统计） https://www.iea.org/reports/energy-and-ai",
    "判定日：by 31 December 2027（2027-12-31）",
    "参考类：Past multi-year data-centre build-out targets",
    "本次运行的默认假设（研究阶段未经询问而采用）：",
    "- End of 2027 means 31 December 2027.",
    "- The IEA year-end estimate resolves the question when published.",
    "- Capacity means IT load in GW, not grid connection requests (单位：吉瓦).",
])
DISCLOSURE_EN = "\n".join([
    "### Operational Definitions and Assumptions",
    "The research run fixed this operational definition of the question at planning time and "
    "disclosed the defaults it chose instead of asking.",
    "- **Outcome:** Global installed data-centre IT capacity is at least 250 GW (≥ 250 GW) on "
    "31 December 2027.",
    "- **Resolution source:** IEA Energy and AI report (official statistic) — "
    "https://www.iea.org/reports/energy-and-ai",
    "- **Deadline:** by 31 December 2027 (2027-12-31)",
    "- **Reference class:** Past multi-year data-centre build-out targets",
    "- **Default assumption (deadline):** End of 2027 means 31 December 2027.",
    "- **Default assumption (resolution source):** The IEA year-end estimate resolves the question "
    "when published.",
    "- **Default assumption (units):** Capacity means IT load in GW, not grid connection requests "
    "(单位：吉瓦).",
])
DISCLOSURE_ZH = "\n".join([
    "### 操作化定义与本次运行的默认假设",
    "研究阶段在制定计划时固定了问题的操作化定义，并披露了未经询问而采用的默认假设。",
    "- **结果定义**：Global installed data-centre IT capacity is at least 250 GW (≥ 250 GW) on "
    "31 December 2027.",
    "- **判定来源**：IEA Energy and AI report（官方统计）— https://www.iea.org/reports/energy-and-ai",
    "- **判定日**：by 31 December 2027（2027-12-31）",
    "- **参考类**：Past multi-year data-centre build-out targets",
    "- **默认假设（判定日）**：End of 2027 means 31 December 2027.",
    "- **默认假设（判定来源）**：The IEA year-end estimate resolves the question when published.",
    "- **默认假设（单位）**：Capacity means IT load in GW, not grid connection requests (单位：吉瓦).",
])
SUMMARY = {
    "spec_sha256": GOLDEN_SHA,
    "horizon_date": SPEC_DAY,
    "outcome_definition": GOLDEN_SPEC["outcome_definition"],
    "resolution_source": {"name": "IEA Energy and AI report", "url": "https://www.iea.org/reports/energy-and-ai",
                          "kind": "official_statistic"},
    "assumptions": [
        {"text": "End of 2027 means 31 December 2027.", "slot": "horizon"},
        {"text": "The IEA year-end estimate resolves the question when published.", "slot": "resolution_source"},
        {"text": "Capacity means IT load in GW, not grid connection requests (单位：吉瓦).", "slot": "units"},
    ],
    "horizon_applied": True,
}
DEADLINE_EN = "- **Deadline:** by 31 December 2027 (2027-12-31)"
DEADLINE_ZH = "- **判定日**：by 31 December 2027（2027-12-31）"
NOT_APPLIED_EN = (" — not applied: this forecast's horizon differs, and the scenario criteria below "
                  "follow that horizon")
NOT_APPLIED_ZH = "——未采用：本预测的判定日与此不同，下列情景判定标准以本预测的判定日为准"


def _spec() -> dict:
    return copy.deepcopy(GOLDEN_SPEC)


def _resigned(spec: dict) -> dict:
    """``spec`` with a recomputed hash (only the field under test makes it unusable)."""
    spec = dict(spec)
    spec["spec_sha256"] = lr.question_spec_sha256(spec)
    return spec


def _actors(spec: bool = True, *, as_of: str = AS_OF, question: str = QUESTION) -> dict:
    actors = {
        "as_of_date": as_of,
        "central_question": question,
        "forecast_inputs": {
            "base_rates": [{"reference_class": "Past build-out targets", "outcome_frequency": "30%",
                            "basis": "IEA tracking"}],
            "indicators": [{"indicator": "IEA year-end capacity estimate", "date_or_trigger": SPEC_DAY,
                            "discriminates": "Upside path"}],
        },
    }
    if spec:
        actors["question_spec"] = _spec()
    return actors


@pytest.fixture
def flag(monkeypatch):
    def _set(on: bool) -> None:
        monkeypatch.setattr(Config, "QUESTION_SPEC_DOWNSTREAM", on, raising=False)
    _set(True)
    return _set


def test_knob_defaults_on_and_is_documented():
    assert Config.QUESTION_SPEC_DOWNSTREAM is True
    knob = config_module.CONFIG_KNOBS["QUESTION_SPEC_DOWNSTREAM"]
    assert (knob["kind"], knob["default"]) == ("bool", "true")
    with open(os.path.join(os.path.dirname(_BACKEND), ".env.example"), encoding="utf-8") as fh:
        assert any(line.startswith("# QUESTION_SPEC_DOWNSTREAM=true ") for line in fh)


# ================================================================ load_question_spec

def test_load_returns_an_independent_copy_of_a_valid_spec(flag):
    actors = _actors()
    loaded = qs.load_question_spec(actors)
    assert loaded == GOLDEN_SPEC
    loaded["assumptions"][0]["text"] = "mutated"
    loaded["horizon"]["date"] = "2099-01-01"
    assert actors["question_spec"] == GOLDEN_SPEC
    assert qs.downstream_spec(actors) == GOLDEN_SPEC
    partial = _resigned({**_spec(), "status": "partial"})
    assert qs.load_question_spec({"question_spec": partial}) == partial


def test_load_rejects_missing_wrong_schema_unavailable_and_sha_mismatch(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.question_spec")
    assert qs.load_question_spec(None) is None
    assert qs.load_question_spec([]) is None
    assert qs.load_question_spec(_actors(spec=False)) is None
    assert qs.load_question_spec({"question_spec": None}) is None
    assert caplog.records == []                          # absent is silent

    unavailable = lr.normalize_question_spec(None, question=QUESTION, as_of=AS_OF, status_if_failed="unavailable")
    assert unavailable["spec_sha256"] == lr.question_spec_sha256(unavailable)      # only the status fails
    tampered = _spec()
    tampered["outcome_definition"] = "Global capacity is at least 200 GW."      # hash left as it was
    rejected = {
        "schema": _resigned({**_spec(), "schema": "drf.question_spec/v2"}),
        "status 'unavailable'": unavailable,
        "status 'bogus'": _resigned({**_spec(), "status": "bogus"}),
        "spec_sha256 mismatch": tampered,
        "no hash": {key: value for key, value in _spec().items() if key != "spec_sha256"},
        "malformed fields": _resigned({**_spec(), "assumptions": "End of 2027"}),
        "not canonical JSON": {**_spec(), "reference_class": float("nan")},
        "not an object": "drf.question_spec/v1",
    }
    for reason, spec in rejected.items():
        caplog.clear()
        assert qs.load_question_spec({"question_spec": spec}) is None, reason
        (record,) = caplog.records
        assert record.levelno == logging.WARNING and "question_spec ignored" in record.getMessage()
    assert "schema 'drf.question_spec/v2'" in qs._rejection(rejected["schema"])
    assert qs._rejection(tampered) == "spec_sha256 mismatch"


def test_flag_off_is_shadow_mode(flag):
    flag(False)
    actors = _actors()
    assert qs.load_question_spec(actors) == GOLDEN_SPEC        # still persisted and loadable
    assert qs.downstream_spec(actors) is None                  # but unused


def test_downstream_spec_degrades_safe_on_an_unexpected_error(flag, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="app.services.question_spec")

    def _boom(actors):
        raise RecursionError("nested too deeply")

    monkeypatch.setattr(qs, "load_question_spec", _boom)
    assert qs.downstream_spec(_actors()) is None
    (record,) = caplog.records
    assert "question_spec ignored (RecursionError" in record.getMessage()


# ================================================================ golden parity

def test_golden_fixture_sha_equals_the_bridge_normalizer():
    """The bridge/backend parity pin on the shared golden fixture: it runs the bridge's own
    normalizer and hash (deerflow_bridge/linear_research.py) against the fixture, so a
    change on the bridge side fails here even though the bridge's test file does not read
    the fixture."""
    spec = lr.normalize_question_spec(GOLDEN["raw_reply"], question=GOLDEN["question"], as_of=GOLDEN["as_of"])
    assert spec == GOLDEN_SPEC
    assert GOLDEN_SPEC["spec_sha256"] == GOLDEN_SHA
    assert lr.question_spec_sha256(GOLDEN_SPEC) == qs.spec_sha256(GOLDEN_SPEC) == GOLDEN_SHA
    assert lr.question_spec_usable(GOLDEN_SPEC) and qs._rejection(GOLDEN_SPEC) == ""
    # The same canonical profile on both sides (non-ASCII text, nesting, key order, numbers).
    for value in (GOLDEN_SPEC, {"b": [1, 2.5, None, True], "a": {"z": "≥ 250 GW", "y": "单位：吉瓦"}},
                  ["x", {"k": -0.0}], "Ω"):
        assert canonical_json_sha256(value) == lr._sha256(lr._canonical_json(value))


# ================================================================ helpers

def test_spec_horizon_date_window():
    spec = _spec()
    assert qs.spec_horizon_date(spec, date(2026, 10, 1)) == date(2027, 12, 31)
    assert qs.spec_horizon_date(spec, datetime(2026, 10, 1, 9, 30)) == date(2027, 12, 31)
    assert qs.spec_horizon_date(spec, date(2027, 12, 30)) == date(2027, 12, 31)
    assert qs.spec_horizon_date(spec, date(2027, 12, 31)) is None          # not after as_of
    assert qs.spec_horizon_date(spec, date(2028, 3, 1)) is None            # already past
    assert qs.spec_horizon_date(spec, date(1997, 12, 31)) == date(2027, 12, 31)   # exactly +30y
    assert qs.spec_horizon_date(spec, date(1997, 12, 30)) is None          # beyond +30y
    leap = {"horizon": {"date": "2054-02-28"}}
    assert qs.spec_horizon_date(leap, date(2024, 2, 29)) == date(2054, 2, 28)     # 29 Feb → 28 Feb
    assert qs.spec_horizon_date({"horizon": {"date": "2054-03-01"}}, date(2024, 2, 29)) is None
    for bad in ({"horizon": {"date": "2027"}}, {"horizon": {"date": "31/12/2027"}},
                {"horizon": {"date": "2027-02-30"}}, {"horizon": {"date": ""}}, {"horizon": "2027-12-31"}, {}):
        assert qs.spec_horizon_date(bad, date(2026, 10, 1)) is None
    assert qs.spec_horizon_date(None, date(2026, 10, 1)) is None
    assert qs.spec_horizon_date(spec, "2026-10-01") is None
    far = date(9990, 1, 1)                                  # the window stops at year 9999, never raises
    assert qs.spec_horizon_date({"horizon": {"date": "9998-06-30"}}, far) == date(9998, 6, 30)
    assert qs.spec_horizon_date({"horizon": {"date": "9999-12-31"}}, far) is None


def test_render_spine_block():
    assert qs.render_spine_block(_spec()) == SPINE_BLOCK
    assert qs.render_spine_block(None) == ""
    only_question = {**_spec(), "outcome_definition": "", "resolution_source": {"name": "", "url": "", "kind": "other"},
                     "horizon": {"label": "", "date": "", "basis": "implied"}, "reference_class": "",
                     "assumptions": []}
    assert qs.render_spine_block(only_question) == ""
    date_only = {"horizon": {"label": "", "date": SPEC_DAY}, "resolution_source": {"name": "Eurostat", "kind": "index"}}
    assert qs.render_spine_block(date_only) == "\n".join([qs.SPINE_BLOCK_HEADER, "判定来源：Eurostat（指数）",
                                                          f"判定日：{SPEC_DAY}"])
    # A line break in a (re-signed) field never splits a prompt line or a Markdown bullet.
    broken = _resigned({**_spec(), "assumptions": [{"text": "Capacity means\nIT load  in GW.", "slot": "units"}]})
    assert qs.load_question_spec({"question_spec": broken}) is not None
    assert qs.render_spine_block(broken).endswith("：\n- Capacity means IT load in GW.")
    assert qs.render_resolution_disclosure(broken, "English").endswith(
        "\n- **Default assumption (units):** Capacity means IT load in GW.")


def test_render_resolution_disclosure_and_summary():
    assert qs.render_resolution_disclosure(_spec(), "English") == DISCLOSURE_EN
    assert qs.render_resolution_disclosure(_spec(), "english (US)") == DISCLOSURE_EN
    assert qs.render_resolution_disclosure(_spec(), "Chinese") == DISCLOSURE_ZH
    assert qs.render_resolution_disclosure(_spec(), "") == DISCLOSURE_ZH
    assert qs.render_resolution_disclosure({"operational_question": "Will X?"}, "English") == ""
    spec = _spec()
    summary = qs.summary(spec)
    assert summary == SUMMARY and tuple(summary) == qs.SUMMARY_KEYS
    summary["assumptions"][0]["text"] = "mutated"
    summary["resolution_source"]["name"] = "mutated"
    assert spec == GOLDEN_SPEC
    assert qs.summary({**spec, "horizon": {"label": "by 2027", "date": ""}})["horizon_date"] is None
    assert qs.summary(spec, horizon_applied=False) == {**SUMMARY, "horizon_applied": False}


def test_summary_copies_only_typed_values():
    """A spec re-signed by another producer passes the integrity checks with mistyped
    fields; forecast.json never carries them."""
    for bad_day in (20271231, "2027-02-30", "31/12/2027", " 2027-12-31", None):
        spec = _resigned({**_spec(), "horizon": {"label": "by 2027", "date": bad_day, "basis": "explicit"}})
        assert qs.load_question_spec({"question_spec": spec}) is not None, bad_day
        assert qs.summary(spec)["horizon_date"] is None, bad_day
        assert DEADLINE_EN not in qs.render_resolution_disclosure(spec, "English")
        assert "判定日：by 2027\n" in qs.render_spine_block(spec)          # the label alone
    for bad_outcome in (42, ["x"], {"text": "x"}, None):
        spec = _resigned({**_spec(), "outcome_definition": bad_outcome})
        assert qs.summary(spec)["outcome_definition"] == "", bad_outcome
    assert qs.summary({**_spec(), "outcome_definition": "At least\n250  GW."})["outcome_definition"] == \
        "At least 250 GW."


def test_disclosure_lead_line_names_defaults_only_when_there_are_some():
    spec = _resigned({**_spec(), "assumptions": []})
    assert qs.load_question_spec({"question_spec": spec}) is not None
    en = qs.render_resolution_disclosure(spec, "English").split("\n")
    assert en[1] == "The research run fixed this operational definition of the question at planning time."
    assert not any(line.startswith("- **Default assumption") for line in en)
    zh = qs.render_resolution_disclosure(spec, "Chinese").split("\n")
    assert zh[1] == "研究阶段在制定计划时固定了问题的操作化定义。"
    assert not any(line.startswith("- **默认假设") for line in zh)
    assert "本次运行的默认假设" not in qs.render_spine_block(spec)
    # With assumptions the lead names them (the pinned DISCLOSURE_* constants).
    assert qs.render_resolution_disclosure(_spec(), "English").split("\n")[1].endswith(
        "and disclosed the defaults it chose instead of asking.")


def test_horizon_applies():
    spec = _spec()
    as_of = date(2026, 10, 1)
    assert qs.horizon_applies(spec, as_of) is True                        # in window, no run horizon
    assert qs.horizon_applies(spec, datetime(2026, 10, 1, 9, 0)) is True
    assert qs.horizon_applies(spec, date(2028, 3, 1)) is False            # already past
    assert qs.horizon_applies(spec, date(1990, 1, 1)) is False            # beyond +30y
    assert qs.horizon_applies(spec, as_of, SPEC_DAY) is True              # the run used it
    assert qs.horizon_applies(spec, as_of, " 2027-12-31 ") is True
    assert qs.horizon_applies(spec, as_of, "2030-12-31") is False         # an explicit prompt date won
    assert qs.horizon_applies(spec, date(2028, 3, 1), SPEC_DAY) is True   # the run horizon is authoritative
    assert qs.horizon_applies(spec, as_of, None) is True
    # Without a valid day (label only, nothing, mistyped) there is nothing to conflict.
    label_only = {**spec, "horizon": {"label": "by the end of 2027", "date": "", "basis": "implied"}}
    for undated in (label_only, {**spec, "horizon": {"date": 20271231}}, {}, None):
        assert qs.horizon_applies(undated, as_of, "2030-12-31") is True
        assert qs.horizon_applies(undated, date(2028, 3, 1)) is True


def test_disclosure_marks_an_unapplied_deadline():
    en = qs.render_resolution_disclosure(_spec(), "English", horizon_applied=False)
    assert en == DISCLOSURE_EN.replace(DEADLINE_EN, DEADLINE_EN + NOT_APPLIED_EN)
    zh = qs.render_resolution_disclosure(_spec(), "Chinese", horizon_applied=False)
    assert zh == DISCLOSURE_ZH.replace(DEADLINE_ZH, DEADLINE_ZH + NOT_APPLIED_ZH)
    # Nothing to mark without a deadline row.
    undated = {**_spec(), "horizon": {"label": "", "date": "", "basis": "implied"}}
    assert qs.render_resolution_disclosure(undated, "English", horizon_applied=False) == \
        qs.render_resolution_disclosure(undated, "English")
    block = fe.render_resolution_block(FORECAST, INDICATORS, language="English", question_spec=_spec(),
                                       question_spec_horizon_applied=False)
    assert DEADLINE_EN + NOT_APPLIED_EN + "\n" in block


# ================================================================ simulation horizon ladder

def _patch_calendar(monkeypatch):
    for name, value in {"SIM_TEMPORAL_MODE": "calendar", "SIM_CALENDAR_TARGET_MAX_ROUNDS": 36,
                        "SIM_CALENDAR_HARD_MAX_ROUNDS": 48, "SIM_HORIZON_DEFAULT_MONTHS": 12,
                        "OASIS_DEFAULT_MAX_ROUNDS": 0}.items():
        monkeypatch.setattr(Config, name, value, raising=False)


def _generator(llm_horizon=None):
    """A bare generator whose LLM horizon rung is a spy (returns ``llm_horizon``)."""
    gen = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    gen.llm_calls = []

    def _llm_rung(context, as_of):
        gen.llm_calls.append((context, as_of))
        return llm_horizon

    gen._llm_extract_horizon = _llm_rung
    return gen


def _timeline(gen, requirement, actors):
    return gen._build_temporal_timeline(requirement, actors, context="background", max_rounds=None)


def test_sim_ladder_prefers_an_explicit_prompt_date_over_the_spec(monkeypatch, flag):
    _patch_calendar(monkeypatch)
    gen = _generator()
    tl = _timeline(gen, "Who leads the data-centre build-out by 2030?", _actors())
    assert (tl.horizon_date, tl.horizon_source) == ("2030-12-31", "bare_year")
    tl = _timeline(gen, QUESTION, _actors(question="Who leads by 2029-06-15?"))     # central_question
    assert (tl.horizon_date, tl.horizon_source) == ("2029-06-15", "explicit_date")
    assert gen.llm_calls == []


def test_sim_ladder_uses_the_spec_date_and_skips_the_llm_rung(monkeypatch, flag):
    _patch_calendar(monkeypatch)
    gen = _generator()
    tl = _timeline(gen, QUESTION, _actors())
    assert (tl.horizon_date, tl.horizon_source, tl.horizon_defaulted) == (SPEC_DAY, "question_spec", False)
    assert tl.horizon_text == "" and tl.as_of_date == AS_OF
    assert tl.round_dates[-1].period_end == SPEC_DAY
    assert gen.llm_calls == []


def test_sim_ladder_ignores_an_out_of_window_spec_date(monkeypatch, flag):
    _patch_calendar(monkeypatch)
    llm = sim_timeline.HorizonResult("2028-09-30", "llm", "", False, 0.7)
    gen = _generator(llm)
    tl = _timeline(gen, QUESTION, _actors(as_of="2028-03-01"))      # the spec's day is already past
    assert (tl.horizon_date, tl.horizon_source) == ("2028-09-30", "llm")
    assert len(gen.llm_calls) == 1


def test_sim_ladder_without_spec_or_flag_off_is_unchanged(monkeypatch, flag):
    _patch_calendar(monkeypatch)
    llm = sim_timeline.HorizonResult("2028-06-30", "llm", "", False, 0.7)
    runs = []
    for on, spec in ((True, False), (False, True), (False, False)):
        flag(on)
        gen = _generator(llm)
        runs.append((asdict(_timeline(gen, QUESTION, _actors(spec=spec))), gen.llm_calls))
    assert runs[0][0]["horizon_source"] == "llm" and len(runs[0][1]) == 1
    assert runs[0] == runs[1] == runs[2]
    flag(True)
    gen = _generator(llm)
    tampered = _actors()
    tampered["question_spec"]["horizon"]["date"] = "2027-06-30"      # fails its hash: ignored
    assert asdict(_timeline(gen, QUESTION, tampered)) == runs[0][0]


def _generate_config(actors):
    """generate_config end to end on a bare generator: no entities, scripted LLM calls."""
    gen = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    gen.provider = gen.model_name = gen.base_url = ""
    prompts = []

    def _llm(prompt, system_prompt):
        prompts.append(prompt)
        return {"horizon_date": "2028-06-30"} if "预测判定日" in prompt else {}

    gen._call_llm_with_retry = _llm
    gen._load_prediction_markets = lambda simulation_id: []
    params = gen.generate_config(simulation_id="sim_qspec", project_id="p", graph_id="g",
                                 simulation_requirement=QUESTION, document_text="Background document.",
                                 entities=[], actors=actors, research_language="English")
    config = json.loads(params.to_json())
    config.pop("generated_at")
    return config, prompts


def test_simulation_config_json_records_question_spec_horizon(monkeypatch, flag):
    _patch_calendar(monkeypatch)
    config, prompts = _generate_config(_actors())
    assert config["temporal_config"]["horizon_source"] == "question_spec"
    assert config["temporal_config"]["horizon_date"] == SPEC_DAY
    assert not any("预测判定日" in prompt for prompt in prompts)

    baseline, base_prompts = _generate_config(_actors(spec=False))
    assert baseline["temporal_config"]["horizon_source"] == "llm"
    assert sum("预测判定日" in prompt for prompt in base_prompts) == 1
    flag(False)
    shadow, shadow_prompts = _generate_config(_actors())
    assert (shadow, shadow_prompts) == (baseline, base_prompts)


# ================================================================ _infer_horizon_date

def test_infer_horizon_date_falls_back_to_the_spec_date(flag):
    infer = po.PipelineOrchestrator._infer_horizon_date
    assert infer(QUESTION, _actors()) == SPEC_DAY
    assert infer("Who leads by 2030?", _actors()) == "2030-12-31"          # deterministic first
    assert infer(QUESTION, _actors(as_of="2028-03-01")) is None             # out of window
    assert infer(QUESTION, _actors(spec=False)) is None
    flag(False)
    assert infer(QUESTION, _actors()) is None


# ================================================================ report: spine, resolution, forecast.json

SPINE_REPLY = {"headline": "h", "horizon": "2027", "confidence": "medium", "scenarios": [
    {"name": name, "probability": p, "summary": f"{name} summary", "key_drivers": ["driver"],
     "resolution_criteria": f"{name} resolves on the IEA estimate for {SPEC_DAY}"}
    for name, p in (("Upside path", 0.5), ("Downside path", 0.3), ("Other / Status Quo", 0.2))]}
BINARY_REPLY = {"binary_forecasts": [{
    "id": "F1", "statement": "Capacity exceeds 250 GW by the end of 2027", "probability": 0.3,
    "resolution_criteria": "The IEA estimate shows at least 250 GW on 2027-12-31",
    "theme": "t1", "horizon_year": 2027}]}


class _RouterLLM(FakeLLMClient):
    """chat_json by prompt: critic -> {}, binary draw -> one binary, anything else -> the spine."""

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier, **kwargs)
        content = messages[-1]["content"]
        if content.startswith(fe._CRITIQUE_INSTRUCTIONS):
            return {}
        if "[Research dossier]" in content:
            return json.loads(json.dumps(BINARY_REPLY))
        return json.loads(json.dumps(SPINE_REPLY))


def _spine_prompts(llm):
    return [c["messages"][-1]["content"] for c in llm.calls
            if c["kind"] == "chat_json" and c["messages"][-1]["content"].startswith(fe._SPINE_LEAD_PREFIX)]


def _agent(llm, actors):
    agent = ReportAgent.__new__(ReportAgent)
    for key, value in {
        "llm": llm, "graph_id": "g1", "simulation_id": "sim_qspec",
        "simulation_requirement": QUESTION, "situation_brief": "Capacity is growing quickly.",
        "actors": actors, "sources": [], "research_report": "# Dossier\n\nBody.", "timeline_events": [],
        "quantitative": [], "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "", "_market_pack": "",
        "_forecast_spine": None, "_forecast_spine_block": "", "_retrieval_query": None,
        "_outline_degraded": False, "_outline_summary": "", "_section_tool_calls": 0,
        "report_logger": None, "console_logger": None, "tools": {}, "hindcast": None,
        "_hindcast_pin_cache": None, "evaluation_context": None, "_evaluation_context_looked_up": True,
        "_evaluation_context_lookup": None, "backbone_check_policy": None,
    }.items():
        setattr(agent, key, value)
    return agent


@pytest.fixture
def report_env(monkeypatch, tmp_path, flag):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "sims"), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"), raising=False)
    for name, value in {
        "REPORT_FORECAST_SELF_CRITIQUE": False, "REPORT_CRITIQUE_BEFORE_PROSE": True,
        "REPORT_PREMORTEM": False, "REPORT_SPINE_SELFCONSISTENCY_K": 1,
        "FORECAST_EMIT_BINARY": True, "FORECAST_BINARY_CONTRARIAN": False,
        "FORECAST_SIM_SENSITIVITY": False, "FORECAST_ENSEMBLE_MODELS": "",
        "PREDICTION_MARKETS_ENABLED": False, "FORECAST_BINARY_THEMES": None,
        "BINARY_FORECASTS_MIN_COUNT": 1, "REPORT_PUBLISH_GATE": False,
        "REPORT_REPAIR_PASSES": False, "REPORT_FORECAST_LEDGER": False,
        "FORECAST_CONTEXT_PACK_BINARY": False, "FORECAST_CONTEXT_PACK_SPINE": False,
        "REPORT_CHRONOLOGY_ASOF_SPLIT": False,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(forecast_ledger, "append_forecast", lambda forecast, **kw: None)
    return tmp_path


def _read(root, report_id, name):
    with open(os.path.join(str(root), "reports", report_id, name), encoding="utf-8") as fh:
        return fh.read()


def _report(root, report_id, actors):
    """Spine, early forecast.json, final forecast.json, then the resolution section."""
    llm = _RouterLLM()
    agent = _agent(llm, actors)
    os.makedirs(os.path.join(str(root), "reports", report_id), exist_ok=True)
    agent._derive_and_pin_forecast_spine(report_id)
    early = json.loads(_read(root, report_id, "forecast.json"))
    agent._finalize_structured_forecast(report_id, "# T\n\nBody text.")
    final = json.loads(_read(root, report_id, "forecast.json"))
    report = SimpleNamespace(markdown_content="# T\n\nBody text.")
    agent._append_resolution_section(report_id, report)
    full = _read(root, report_id, "full_report.md")
    assert full == report.markdown_content
    (spine_prompt,) = _spine_prompts(llm)
    return SimpleNamespace(prompt=spine_prompt, early=early, final=final, full=full)


def test_spine_prompt_carries_the_spec_block_only_with_a_spec_and_the_flag(report_env, flag):
    with_spec = _report(report_env, "r_spec", _actors())
    without = _report(report_env, "r_plain", _actors(spec=False))
    assert SPINE_BLOCK in with_spec.prompt and qs.SPINE_BLOCK_HEADER not in without.prompt
    # First in the research inputs (the input cap keeps it), and nothing else changes.
    label = "[研究输入：参考类基率 / 观察指标]\n"
    assert label + SPINE_BLOCK + "\n\n## 预测输入" in with_spec.prompt
    assert with_spec.prompt.replace(SPINE_BLOCK + "\n\n", "", 1) == without.prompt
    flag(False)
    shadow = _report(report_env, "r_shadow", _actors())
    assert shadow.prompt == without.prompt


def test_spine_block_reaches_the_shared_spine_kwargs(report_env, monkeypatch):
    """EVAL-11's backbone check rebuilds the prompt from the same spine_kwargs."""
    seen = {}

    def _check(self, pre_critique_spine, spine_kwargs, *, spine_served_by=None):
        seen["kwargs"] = dict(spine_kwargs)

    monkeypatch.setattr(ReportAgent, "_run_backbone_check", _check)
    run = _report(report_env, "r_kwargs", _actors())
    assert set(seen["kwargs"]) == {"central_question", "horizon", "situation_brief", "forecast_inputs",
                                   "signal_pack", "market_block", "language"}
    assert seen["kwargs"]["forecast_inputs"].startswith(SPINE_BLOCK + "\n\n## 预测输入")
    assert fe.build_spine_user_prompt(**seen["kwargs"])[0] == run.prompt


def test_spine_block_alone_when_research_has_no_forecast_inputs(report_env):
    actors = _actors()
    del actors["forecast_inputs"]
    run = _report(report_env, "r_alone", actors)
    assert "\n\n[研究输入]\n" + SPINE_BLOCK + "\n\n[" in run.prompt


def test_structured_spine_omissions_characterization_stays_green():
    """The spec block reaches the spine through forecast_inputs: no new kwarg, and the
    WP6 characterization (no base_distribution= / quantitative_facts=) still holds."""
    from test_architecture_characterization import test_characterizes_structured_spine_omissions
    test_characterizes_structured_spine_omissions()
    assert set(inspect.signature(fe.build_spine_user_prompt).parameters) == {
        "central_question", "horizon", "situation_brief", "forecast_inputs", "signal_pack",
        "base_distribution", "quantitative_facts", "market_block", "context_pack", "language"}
    assert set(inspect.signature(fe.derive_forecast_spine).parameters) == {
        "llm", "central_question", "horizon", "situation_brief", "forecast_inputs", "signal_pack",
        "base_distribution", "quantitative_facts", "market_block", "context_pack", "language"}


def test_forecast_json_carries_the_summary_and_the_publish_gate_is_unchanged(report_env, flag):
    with_spec = _report(report_env, "r_fc_spec", _actors())
    without = _report(report_env, "r_fc_plain", _actors(spec=False))
    assert with_spec.final["question_spec"] == SUMMARY
    assert "question_spec" not in with_spec.early              # final write only
    assert "question_spec" not in without.final
    stripped = {key: value for key, value in with_spec.final.items() if key != "question_spec"}
    assert stripped == without.final
    gated = ReportAgent._apply_publish_gate(copy.deepcopy(with_spec.final))
    gated_plain = ReportAgent._apply_publish_gate(copy.deepcopy(without.final))
    assert {key: value for key, value in gated.items() if key != "question_spec"} == gated_plain
    flag(False)
    shadow = _report(report_env, "r_fc_shadow", _actors())
    assert shadow.final == without.final and shadow.early == without.early


def test_full_report_resolution_section_lists_definitions_and_every_assumption(report_env, flag):
    with_spec = _report(report_env, "r_rs_spec", _actors())
    without = _report(report_env, "r_rs_plain", _actors(spec=False))
    assert DISCLOSURE_EN in with_spec.full
    for row in GOLDEN_SPEC["assumptions"]:
        assert row["text"] in with_spec.full
    head = ("## How to Verify This Forecast (Resolution Criteria & Indicators)\n"
            "This section lists **falsifiable, trackable** resolution criteria for each scenario, "
            "plus dated/triggered indicators for future scoring and calibration.\n\n")
    assert head + DISCLOSURE_EN + "\n\n### Per-Scenario Resolution Criteria\n" in with_spec.full
    assert with_spec.full.replace(DISCLOSURE_EN + "\n\n", "", 1) == without.full
    flag(False)
    assert _report(report_env, "r_rs_shadow", _actors()).full == without.full


@contextmanager
def _report_agent_warnings():
    """WARNING messages of 'mirofish.report_agent' (that logger does not propagate, so
    caplog never sees them)."""

    class _Probe(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.WARNING)
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    probe = _Probe()
    target = logging.getLogger("mirofish.report_agent")
    target.addHandler(probe)
    try:
        yield probe.messages
    finally:
        target.removeHandler(probe)


def _calendar_horizon(root, horizon_date):
    """The simulation's calendar temporal_config (what ReportAgent._temporal_horizon_date reads)."""
    sim_dir = os.path.join(str(root), "sims", "sim_qspec")
    os.makedirs(sim_dir, exist_ok=True)
    with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as fh:
        json.dump({"temporal_config": {"mode": "calendar", "horizon_date": horizon_date}}, fh)


def test_a_spec_deadline_that_is_not_the_run_horizon_never_reaches_the_spine(report_env):
    _calendar_horizon(report_env, "2030-12-31")        # e.g. "Who leads by 2030?" won the sim ladder
    with _report_agent_warnings() as warnings:
        conflict = _report(report_env, "r_hz_conflict", _actors())
    (note,) = [message for message in warnings if "研究问题规范判定日" in message]     # logged once
    assert f"{SPEC_DAY} 不是本次运行的判定日 2030-12-31" in note
    plain = _report(report_env, "r_hz_plain", _actors(spec=False))
    assert "[预测时间范围]\n2030-12-31" in conflict.prompt
    assert conflict.prompt == plain.prompt              # no spec block, so no second deadline
    assert conflict.final["question_spec"] == {**SUMMARY, "horizon_applied": False}
    assert DISCLOSURE_EN.replace(DEADLINE_EN, DEADLINE_EN + NOT_APPLIED_EN) in conflict.full


def test_a_spec_deadline_the_run_used_is_applied(report_env):
    _calendar_horizon(report_env, SPEC_DAY)
    with _report_agent_warnings() as warnings:
        run = _report(report_env, "r_hz_same", _actors())
    assert not [message for message in warnings if "研究问题规范判定日" in message]
    assert f"[预测时间范围]\n{SPEC_DAY}" in run.prompt and SPINE_BLOCK in run.prompt
    assert run.final["question_spec"] == SUMMARY
    assert DISCLOSURE_EN in run.full and NOT_APPLIED_EN not in run.full


def test_an_out_of_window_spec_deadline_is_not_applied_without_a_calendar(report_env):
    with _report_agent_warnings() as warnings:
        run = _report(report_env, "r_hz_past", _actors(as_of="2028-03-01"))
    (note,) = [message for message in warnings if "研究问题规范判定日" in message]
    assert f"{SPEC_DAY} 不在 as_of 2028-03-01 之后 30 年窗口内" in note
    plain = _report(report_env, "r_hz_past_plain", _actors(spec=False, as_of="2028-03-01"))
    assert qs.SPINE_BLOCK_HEADER not in run.prompt and run.prompt == plain.prompt
    assert run.final["question_spec"] == {**SUMMARY, "horizon_applied": False}
    assert DEADLINE_EN + NOT_APPLIED_EN + "\n" in run.full


def test_spine_block_logs_when_it_pushes_research_inputs_past_the_cap(report_env, monkeypatch):
    actors = _actors()
    with _report_agent_warnings() as warnings:
        _report(report_env, "r_cap_default", actors)
    assert not [message for message in warnings if "REPORT_SPINE_INPUT_CAP_INPUTS" in message]
    cap = len(SPINE_BLOCK) + 10
    monkeypatch.setattr(Config, "REPORT_SPINE_INPUT_CAP_INPUTS", cap, raising=False)
    with _report_agent_warnings() as warnings:
        run = _report(report_env, "r_cap_small", actors)
    (note,) = [message for message in warnings if "REPORT_SPINE_INPUT_CAP_INPUTS" in message]
    inputs = SPINE_BLOCK + "\n\n" + forecast_inputs_block(actors)
    assert f"（{len(SPINE_BLOCK)} 字）" in note and f"共 {len(inputs)} 字" in note
    assert f"={cap}，末尾 {len(inputs) - cap} 字被截断" in note
    assert SPINE_BLOCK + "\n\n" + inputs[len(SPINE_BLOCK) + 2:cap] + "\n\n[" in run.prompt   # block kept, tail cut


FORECAST = {"scenarios": [{"name": "Upside path", "probability": 0.6, "resolution_criteria": "IEA ≥ 250 GW"},
                          {"name": "Other / Status Quo", "probability": 0.4, "resolution_criteria": ""}]}
INDICATORS = [{"indicator": "IEA estimate", "date_or_trigger": SPEC_DAY, "discriminates": "Upside path"}]
LEGACY_EN = "\n".join([
    "## How to Verify This Forecast (Resolution Criteria & Indicators)",
    "This section lists **falsifiable, trackable** resolution criteria for each scenario, "
    "plus dated/triggered indicators for future scoring and calibration.",
    "",
    "### Per-Scenario Resolution Criteria",
    "- **[60%] Upside path**: IEA ≥ 250 GW",
    "- **[40%] Other / Status Quo**: (no explicit resolution criteria — needs completion)",
    "",
    "### Indicators to Watch (check at expiry/trigger)",
    "| Indicator | Due / trigger | Discriminates scenario |",
    "|---|---|---|",
    f"| IEA estimate | {SPEC_DAY} | Upside path |",
])
LEGACY_ZH = "\n".join([
    "## 如何验证本预测（判定标准与观察指标）",
    "本节给出每个情景**可证伪、可追踪**的判定标准与到期/触发型观察指标，供日后核对与校准。",
    "",
    "### 各情景判定标准",
    "- **[60%] Upside path**：IEA ≥ 250 GW",
    "- **[40%] Other / Status Quo**：（缺明确判定标准——需补全）",
    "",
    "### 观察指标（到期/触发即核对）",
    "| 指标 | 到期/触发 | 关联情景 |",
    "|---|---|---|",
    f"| IEA estimate | {SPEC_DAY} | Upside path |",
])


def test_render_resolution_block_inserts_the_disclosure_en_and_zh():
    en = fe.render_resolution_block(FORECAST, INDICATORS, language="English", question_spec=_spec())
    split = LEGACY_EN.index("### Per-Scenario")
    assert en == LEGACY_EN[:split] + DISCLOSURE_EN + "\n\n" + LEGACY_EN[split:]
    zh = fe.render_resolution_block(FORECAST, INDICATORS, language="Chinese", question_spec=_spec())
    split = LEGACY_ZH.index("### 各情景判定标准")
    assert zh == LEGACY_ZH[:split] + DISCLOSURE_ZH + "\n\n" + LEGACY_ZH[split:]


def test_render_resolution_block_without_spec_is_byte_identical():
    assert fe.render_resolution_block(FORECAST, INDICATORS, language="English") == LEGACY_EN
    assert fe.render_resolution_block(FORECAST, INDICATORS, language="English", question_spec=None) == LEGACY_EN
    assert fe.render_resolution_block(FORECAST, INDICATORS) == LEGACY_ZH
    # A spec with nothing to disclose adds nothing; no scenarios still renders nothing.
    assert fe.render_resolution_block(FORECAST, INDICATORS, "English", question_spec={}) == LEGACY_EN
    assert fe.render_resolution_block({"scenarios": []}, question_spec=_spec()) == ""


# ================================================================ actors.json → consumers

def test_question_spec_survives_into_report_agent_and_simulation_inputs(report_env, tmp_path, monkeypatch):
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (handoff / "research_report.md").write_text("# Dossier\n\n" + "Research finding line.\n" * 40,
                                                encoding="utf-8")
    (handoff / "actors.json").write_text(json.dumps(_actors(), ensure_ascii=False, indent=2), encoding="utf-8")
    actors = po._load_research_handoff(str(handoff))["actors"]
    actors, _audit = po._reconcile_research_cast(actors)
    assert actors["question_spec"] == GOLDEN_SPEC

    agent = ReportAgent(graph_id="g1", simulation_id="sim_ctor", simulation_requirement=QUESTION,
                        llm_client=FakeLLMClient(), zep_tools=object(), actors=actors)
    assert agent.actors["question_spec"] == GOLDEN_SPEC and qs.downstream_spec(agent.actors) == GOLDEN_SPEC

    # SimulationManager.prepare_simulation hands the same object to generate_config.
    dossier = acr._dossier()
    dossier["question_spec"] = _spec()
    entities = [acr._entity(actor) for actor in dossier["actors"]]
    seen = {}

    class _Reader:
        def filter_defined_entities(self, **kwargs):
            return FilteredEntities(entities=entities, entity_types={"Organization"}, total_count=2,
                                    filtered_count=2)

    def _generate_config(self, **kwargs):
        seen["actors"] = kwargs["actors"]
        return SimulationParameters(
            simulation_id=kwargs["simulation_id"], project_id=kwargs["project_id"],
            graph_id=kwargs["graph_id"], simulation_requirement=kwargs["simulation_requirement"],
            agent_configs=[AgentActivityConfig(agent_id=i, entity_uuid=e.uuid, entity_name=e.name,
                                               entity_type="Organization")
                           for i, e in enumerate(kwargs["entities"])])

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "sims"))
    monkeypatch.setattr("app.services.simulation_manager.ZepEntityReader", _Reader)
    monkeypatch.setattr("app.services.simulation_manager.SimulationConfigGenerator.generate_config",
                        _generate_config)
    monkeypatch.setattr(OasisProfileGenerator, "_build_entity_context", lambda self, entity: "")
    monkeypatch.setattr(OasisProfileGenerator, "_print_generated_profile", lambda *a, **k: None)
    monkeypatch.setattr(Config, "ACTOR_CAST_MAX", 20, raising=False)
    monkeypatch.setattr(Config, "OASIS_MAX_AGENTS", 80, raising=False)
    monkeypatch.setattr(Config, "SIM_AUDIENCE_AGENTS", 0, raising=False)
    manager = SimulationManager()
    created = manager.create_simulation(project_id="p", graph_id="g", enable_twitter=True, enable_reddit=True)
    manager.prepare_simulation(created.simulation_id, simulation_requirement="Model the grid permit",
                               document_text=acr.REPORT, use_llm_for_profiles=False, actors=dossier,
                               research_language="English")
    assert seen["actors"]["question_spec"] == GOLDEN_SPEC
    assert qs.downstream_spec(seen["actors"]) == GOLDEN_SPEC
