"""EVAL-11 (P15): shadow cross-backbone sensitivity check of the forecast spine.

Covers the byte-identical extraction of the spine prompt builders from
derive_forecast_spine, the pure agreement/classification metrics, the check itself (a
pinned uncached same-backbone control plus one distinct secondary backbone on the
fixed-scenario follow prompt; BudgetExceeded and PipelineCancelled propagate, other errors
are recorded as unchecked), the report-level hook (shadow record in
forecast.quality.backbone_sensitivity with published probabilities unchanged; nothing at all
with the policy off) and the admission pin in safety_policy_v1 (never re-captured on resume).

Offline: FakeLLMClient-based stubs and a fake OpenAI transport; no network, no real LLM.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import logging
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import backbone_sensitivity as bs
from app.services import forecast_extractor as fe
from app.services import pipeline_orchestrator as po
from app.services.report_agent import ReportAgent, ReportManager
from app.utils import actors as actors_mod
from app.utils import llm_client as lc
from app.utils import telemetry as tel
from app.utils.telemetry import BudgetExceeded
from tests.conftest import FakeLLMClient

_BACKEND = Path(__file__).resolve().parents[1]
_FOLLOW_MARKER = "[已确定情景集合"
_NAMES = ("Rapid adoption path", "Gradual adoption path", "Other / Status Quo")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows(probs, names=_NAMES):
    return [
        {"name": name, "probability": p, "summary": f"{name} summary",
         "key_drivers": ["driver"],
         "resolution_criteria": f"{name} resolves if the index is above {10 + i}% by 2030"}
        for i, (name, p) in enumerate(zip(names, probs, strict=True))
    ]


def _spine(probs=(0.5, 0.3, 0.2), names=_NAMES):
    return {"headline": "Adoption outlook", "horizon": "2030", "confidence": "medium",
            "confidence_rationale": "Evidence is mixed.", "key_uncertainties": ["policy"],
            "scenarios": _rows(list(probs), names), "schema_version": 1}


# =============================================================== 1. prompt builder extraction
_FULL_INPUTS = actors_mod.forecast_inputs_block({"forecast_inputs": {
    "base_rates": [{"reference_class": "tariff rounds", "outcome_frequency": "30%"}],
    "drivers": [{"variable": "inflation", "direction": "up"}],
    "indicators": [{"indicator": "CPI", "date_or_trigger": "2027-01"}],
    "scenarios": [{"name": "base", "probability_band": "40-60%", "narrative": "n"}],
}})
_CASES = {
    # every block, every input over its cap, the WorldState anchor on (one unparsable share)
    "rich": {"central_question": "Q" * 700, "horizon": "H" * 200, "situation_brief": "B" * 2500,
             "forecast_inputs": _FULL_INPUTS + "I" * 7000, "signal_pack": "S" * 7000,
             "base_distribution": {"Rapid build-out": 0.6, "Stall": 0.4, "bad": "x"},
             "quantitative_facts": "F" * 3500, "market_block": "M" * 7000},
    "small": {"central_question": "q", "horizon": "2030", "forecast_inputs": "notes",
              "market_block": "| m | 30% |"},
}
_GOLDEN_NAMES = ("Rapid build-out", "Stall")
# sha256 of derive_forecast_spine's (first draw, K=2 follow draw) prompts, captured from the
# code before the builders were extracted (REPORT_ABSENCE_MARKERS on and off).
_GOLDEN_SHA = {
    (True, "rich"): ("bd84c27b7f94a33283906100087c3960beab65ae93299eb58d0b2288b83efe94",
                     "9e8bf4a72ef56dbedcedbe36ed15e75061e4bc3022a3982326122729c85bea9f"),
    (True, "small"): ("a1c07e7c56eaf0ebf42b41faaf75ec6a8a505a63711b033b43db20dea1adfdad",
                      "c893ac5e4c2b762951f172ea16d3242c844a4535213471195edd31e81ef3c7cf"),
    (False, "rich"): ("7ce7d5305355b4ea3de9611b07105b36b80d4de68404c44ac5d393dd0a873064",
                      "be08794ee53fb3fe66c0e6da5f788f0331915fe82cf3224eb834e908cafb4a50"),
    (False, "small"): ("3e6df54e289ff0e5558ef6aa28cb9d68f2d22275249e40c097dd63a5f1457dc3",
                       "e912aee21f01a5443bbcd4c3be6c6b9a07c5a140ac0c626ef0360052d66f20ff"),
}
# The golden string: markers off, small inputs (the legacy instructions plus these blocks).
_GOLDEN_SMALL_LEGACY_TAIL = (
    "\n\n[核心问题]\nq\n\n[预测时间范围]\n2030"
    "\n\n[研究输入：参考类基率 / 驱动因素 / 观察指标 / 候选情景]\nnotes"
    "\n\n[预测市场隐含概率（Polymarket 实盘·校准锚点，非真值）]\n| m | 30% |"
    "\n与上述市场重叠的情景，其概率须对照市场隐含概率；偏离超过 10 个百分点时"
    "在 adjustment_rationale 中显式解释分歧（市场遗漏/错价了什么）。")
_GOLDEN_FOLLOW_TAIL = ("\n\n[已确定情景集合：请沿用完全相同的情景名，仅独立重新估计各自概率"
                       "（其和≈1），不要新增或重命名情景]\nRapid build-out；Stall")


@pytest.mark.parametrize("markers", [True, False], ids=["markers_on", "markers_off"])
@pytest.mark.parametrize("case", sorted(_CASES))
def test_spine_prompt_builder_byte_identical(monkeypatch, markers, case):
    monkeypatch.setattr(Config, "REPORT_ABSENCE_MARKERS", markers, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_ANCHOR_WORLDSTATE", True, raising=False)
    kwargs = _CASES[case]
    fake = FakeLLMClient(json_responses=[_spine((0.6, 0.4), _GOLDEN_NAMES) for _ in range(2)])
    fe.derive_forecast_spine(fake, **kwargs)
    assert len(fake.calls) == 2
    first, follow = (call["messages"][0]["content"] for call in fake.calls)

    user, anchor_ws = fe.build_spine_user_prompt(**kwargs)
    assert user == first
    assert fe.spine_follow_prompt(user, list(_GOLDEN_NAMES)) == follow
    assert anchor_ws is (case == "rich")
    assert (_sha(first), _sha(follow)) == _GOLDEN_SHA[(markers, case)]
    if (markers, case) == (False, "small"):
        assert first == fe._SPINE_INSTRUCTIONS + _GOLDEN_SMALL_LEGACY_TAIL
        assert follow == first + _GOLDEN_FOLLOW_TAIL


def test_builder_signature_mirrors_derive_forecast_spine():
    builder = inspect.signature(fe.build_spine_user_prompt).parameters
    derive = inspect.signature(fe.derive_forecast_spine).parameters
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in builder.values())
    assert ([(name, p.default) for name, p in builder.items()]
            == [(name, p.default) for name, p in derive.items() if name != "llm"])
    assert fe.build_spine_user_prompt() == (fe.build_spine_user_prompt(
        central_question="", horizon="", situation_brief=None, forecast_inputs="",
        signal_pack="", base_distribution=None, quantitative_facts="", market_block=""))


# =============================================================== 2. pure metrics
def _named(pairs):
    return {"scenarios": [{"name": n, "probability": p} for n, p in pairs]}


def test_scenario_agreement_values():
    a = _named([("Alpha", 0.5), ("Beta", 0.3), ("Gamma", 0.2)])
    b = _named([("alpha.", 0.3), ("BETA", 0.5), ("Delta", 0.2)])
    ag = bs.scenario_agreement(a, b)
    assert ag == {
        "tv": 0.4,
        "leader_agree": False,
        "leaders": {"a": ["alpha"], "b": ["beta"]},
        "per_scenario_abs_delta": {"alpha": 0.2, "beta": 0.2, "gamma": 0.2, "delta": 0.2},
        "max_abs_delta": 0.2,
        "matched": 2,
        "missing": ["gamma", "delta"],
    }
    same = bs.scenario_agreement(a, copy.deepcopy(a))
    assert (same["tv"], same["max_abs_delta"], same["matched"], same["missing"],
            same["leader_agree"]) == (0.0, 0.0, 3, [], True)
    # a shared lead (tie) agrees whatever the row order
    tie = bs.scenario_agreement(_named([("A", 0.4), ("B", 0.4), ("C", 0.2)]),
                                _named([("B", 0.4), ("A", 0.4), ("C", 0.2)]))
    assert tie["leader_agree"] is True and tie["tv"] == 0.0
    # small moves: 0.5 -> 0.45 on two scenarios
    small = bs.scenario_agreement(_named([("A", 0.5), ("B", 0.5)]),
                                  _named([("A", 0.55), ("B", 0.45)]))
    assert (small["tv"], small["max_abs_delta"], small["leader_agree"]) == (0.05, 0.05, True)


def test_scenario_agreement_skips_unreadable_rows():
    junk = {"scenarios": [
        "not a row", {"name": "", "probability": 0.2}, {"name": "A", "probability": float("nan")},
        {"name": "B", "probability": True}, {"name": "C", "probability": "0.3"},
        {"name": "C", "probability": 0.9}, {"name": "D", "probability": 0.7},
    ]}
    ag = bs.scenario_agreement(junk, _named([("C", 0.3), ("D", 0.7)]))
    assert (ag["matched"], ag["tv"], ag["missing"]) == (2, 0.0, [])  # "0.3" parses; first C wins
    empty = bs.scenario_agreement({}, None)
    assert empty == {"tv": 0.0, "leader_agree": False, "leaders": {"a": [], "b": []},
                     "per_scenario_abs_delta": {}, "max_abs_delta": 0.0, "matched": 0,
                     "missing": []}


def _ag(leader_agree=True, max_abs_delta=0.0, matched=3):
    return {"leader_agree": leader_agree, "max_abs_delta": max_abs_delta, "matched": matched}


@pytest.mark.parametrize("cross, within, threshold, expected", [
    (_ag(), _ag(), 0.15, "stable"),
    (_ag(max_abs_delta=0.1499), _ag(max_abs_delta=0.1499), 0.15, "stable"),
    (_ag(max_abs_delta=0.15), _ag(max_abs_delta=0.05), 0.15, "backbone_sensitive"),
    (_ag(leader_agree=False, max_abs_delta=0.02), _ag(), 0.15, "backbone_sensitive"),
    (_ag(), _ag(max_abs_delta=0.2), 0.15, "unstable_within_backbone"),
    (_ag(max_abs_delta=0.3), _ag(max_abs_delta=0.2), 0.15, "unstable_within_backbone"),
    (_ag(leader_agree=False), _ag(leader_agree=False), 0.15, "unstable_within_backbone"),
    (_ag(max_abs_delta=0.3), _ag(max_abs_delta=0.2), 0.5, "stable"),
    (_ag(), _ag(), 0, "unchecked:invalid_threshold"),
    (_ag(), _ag(), 1.5, "unchecked:invalid_threshold"),
    (_ag(), _ag(), None, "unchecked:invalid_threshold"),
    (_ag(), _ag(), float("nan"), "unchecked:invalid_threshold"),
    (_ag(), _ag(), "abc", "unchecked:invalid_threshold"),
    (None, _ag(), 0.15, "unchecked:missing:cross"),
    (_ag(), "junk", 0.15, "unchecked:missing:within"),
    (_ag(matched=0), _ag(), 0.15, "unchecked:no_matched_scenarios:cross"),
    (_ag(), _ag(matched=0), 0.15, "unchecked:no_matched_scenarios:within"),
])
def test_classify_matrix(cross, within, threshold, expected):
    assert bs.classify(cross, within, threshold) == expected


# =============================================================== 3. the check (fakes)
class _ScriptedLLM(FakeLLMClient):
    """FakeLLMClient serving scripted chat_json replies (an exception is raised); every call
    logs the serving instance's backbone state. copy.copy shares the reply and log lists, so a
    control copy draws from its primary's script."""

    def __init__(self, replies, provider="primary", model="p-1", log=None):
        super().__init__(provider=provider, model=model)
        self.replies = list(replies)
        self.log = log if log is not None else []

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier,
                          **kwargs)
        self.log.append({
            "provider": self.provider, "model": self.model,
            "pinned": getattr(self, "_pinned", None), "use_cache": getattr(self, "use_cache", None),
            "prompt": messages[-1]["content"], "temperature": temperature,
            "max_tokens": max_tokens, "stage": tel.get_run_context()[1],
        })
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, BaseException):
            raise reply
        return copy.deepcopy(reply)


class _Factory:
    """client_factory stand-in: provider name -> scripted client (or an exception)."""

    def __init__(self, table, log):
        self.table, self.log, self.built, self.asked = table, log, {}, []

    def __call__(self, name):
        self.asked.append(name)
        spec = self.table[name]
        if isinstance(spec, BaseException):
            raise spec
        model, replies = spec
        client = _ScriptedLLM(replies, provider=name, model=model, log=self.log)
        self.built[name] = client
        return client


def _check(control_reply, secondary_reply, *, providers=("other",), table=None,
           max_abs_delta=0.15, primary_spine=None):
    log = []
    primary = _ScriptedLLM([control_reply], log=log)
    factory = _Factory(table or {"other": ("o-1", [secondary_reply])}, log)
    result = bs.run_spine_backbone_check(
        follow_prompt="FOLLOW PROMPT", primary_spine=primary_spine or _spine(),
        primary_llm=primary, providers=list(providers), client_factory=factory,
        max_tokens=6144, max_abs_delta=max_abs_delta)
    return result, primary, factory, log


def test_secondary_flip_is_backbone_sensitive():
    result, primary, factory, log = _check(_spine(), _spine((0.3, 0.5, 0.2)))

    assert result["schema"] == "backbone-sensitivity/v1"
    assert result["note"] == "shadow diagnostic; probabilities unchanged"
    assert result["status"] == "backbone_sensitive"
    assert result["providers"] == {
        "primary": {"provider": "primary", "model": "p-1", "served_model": None,
                    "spine_served_by": None},
        "secondary": {"provider": "other", "model": "o-1", "served_model": None}}
    assert result["within_basis"] == bs.WITHIN_BASIS
    # the pinned threshold is its own key; max_abs_delta only ever names an observed maximum
    assert (result["calls"], result["threshold"], result["skipped"]) == (2, 0.15, [])
    assert "max_abs_delta" not in result
    assert result["cross"]["leader_agree"] is False and result["cross"]["max_abs_delta"] == 0.2
    assert result["within"]["tv"] == 0.0 and result["within"]["leader_agree"] is True
    # one control draw (the primary backbone, pinned + uncached) then one secondary draw, both
    # on the identical follow prompt at the spine temperature
    assert [(c["provider"], c["model"], c["pinned"], c["use_cache"]) for c in log] == [
        ("primary", "p-1", True, False), ("other", "o-1", True, False)]
    assert {(c["prompt"], c["temperature"], c["max_tokens"]) for c in log} == {
        ("FOLLOW PROMPT", 0.2, 6144)}
    # the primary client itself is untouched (the control is a copy)
    assert primary.model == "p-1" and not hasattr(primary, "_pinned")


def test_control_flip_is_unstable_within_backbone():
    result, *_ = _check(_spine((0.3, 0.5, 0.2)), _spine((0.3, 0.5, 0.2)))
    assert result["status"] == "unstable_within_backbone"
    assert result["cross"]["tv"] == 0.0 and result["within"]["leader_agree"] is False
    stable, *_ = _check(_spine((0.45, 0.35, 0.2)), _spine((0.55, 0.25, 0.2)))
    assert stable["status"] == "stable"
    assert (stable["within"]["max_abs_delta"], stable["cross"]["max_abs_delta"]) == (0.05, 0.1)


def test_control_uses_the_primary_strong_tier_model():
    log = []

    class _Tiered(_ScriptedLLM):
        def _model_for_tier(self, tier, *, pinned=None):
            return "p-strong" if tier == "strong" else "p-fast"

    primary = _Tiered([_spine()], log=log)
    table = {"same": ("p-strong", []), "other": ("o-1", [_spine()])}
    factory = _Factory({"primary": table["same"], "other": table["other"]}, log)
    result = bs.run_spine_backbone_check(
        follow_prompt="F", primary_spine=_spine(), primary_llm=primary,
        providers="primary,other", client_factory=factory, max_tokens=100)
    # the served model, not LLM_MODEL_NAME, is the primary identity: "primary"/"p-strong" is
    # the same backbone and is skipped; the control runs on p-strong
    assert result["providers"]["primary"] == {"provider": "primary", "model": "p-strong",
                                              "served_model": None, "spine_served_by": None}
    assert result["skipped"] == [{"provider": "primary", "reason": "same_as_primary"}]
    assert [c["model"] for c in log] == ["p-strong", "o-1"]
    assert primary.model == "p-1" and result["status"] == "stable"

    # a CLI subscription primary is served its own model (the tier alias is metering only)
    cli_log = []
    cli = _Tiered([_spine()], provider="claude-cli", model="claude-opus", log=cli_log)
    cli_result = bs.run_spine_backbone_check(
        follow_prompt="F", primary_spine=_spine(), primary_llm=cli, providers=["other"],
        client_factory=_Factory({"other": ("o-1", [_spine()])}, cli_log), max_tokens=100)
    assert cli_result["providers"]["primary"] == {"provider": "claude-cli", "model": "claude-opus",
                                                  "served_model": None, "spine_served_by": None}
    assert [(c["provider"], c["model"]) for c in cli_log] == [
        ("claude-cli", "claude-opus"), ("other", "o-1")]


def test_same_provider_unchecked():
    table = {"primary": ("p-1", [_spine()]), "broken": ValueError("no key")}
    result, _primary, factory, log = _check(
        _spine(), None, providers=("Primary", "primary ", "", "broken"), table=table)
    assert result["status"] == "unchecked:no_distinct_secondary"
    assert result["calls"] == 0 and log == []  # no secondary backbone -> no LLM call at all
    assert result["providers"]["secondary"] is None and result["cross"] is None
    assert result["skipped"] == [{"provider": "primary", "reason": "same_as_primary"},
                                 {"provider": "broken", "reason": "construct_failed:ValueError"}]
    assert factory.asked == ["primary", "broken"]  # de-duplicated, blanks dropped
    empty, *_ = _check(_spine(), None, providers=(), table={})
    assert empty["status"] == "unchecked:no_distinct_secondary" and empty["calls"] == 0
    # the same provider label on a different model is a distinct backbone
    other_model, *_ = _check(_spine(), None, providers=("primary",),
                             table={"primary": ("p-2", [_spine()])})
    assert other_model["providers"]["secondary"] == {"provider": "primary", "model": "p-2",
                                                     "served_model": None}
    assert other_model["status"] == "stable"


def test_parse_and_policy_helpers():
    assert bs.parse_providers(" DeepSeek, openai,,deepseek ,glm ") == ["deepseek", "openai", "glm"]
    assert bs.parse_providers(["Kimi", None, "kimi"]) == ["kimi"]
    assert bs.parse_providers(None) == []
    cfg = SimpleNamespace(BACKBONE_CHECK_ENABLED=True, BACKBONE_CHECK_PROVIDERS="glm, kimi",
                          BACKBONE_CHECK_MAX_ABS_DELTA=0.2)
    assert bs.capture_policy(cfg) == {"enabled": True, "providers": ["glm", "kimi"],
                                      "max_abs_delta": 0.2}
    assert bs.enabled_policy(bs.capture_policy(cfg)) == bs.capture_policy(cfg)
    for disabled in (None, "junk", {}, {"enabled": False, "providers": ["glm"]},
                     {"enabled": "true"}, {"enabled": 1}, bs.DISABLED_POLICY):
        assert bs.enabled_policy(disabled) is None


def test_capture_policy_warns_on_invalid_threshold_at_admission(caplog):
    def cfg(enabled, delta):
        return SimpleNamespace(BACKBONE_CHECK_ENABLED=enabled, BACKBONE_CHECK_PROVIDERS="glm",
                               BACKBONE_CHECK_MAX_ABS_DELTA=delta)

    with caplog.at_level(logging.WARNING, logger=bs.logger.name):
        assert bs.capture_policy(cfg(True, float("nan")))["max_abs_delta"] is None
        assert bs.capture_policy(cfg(True, 1.5))["max_abs_delta"] == 1.5
    warnings = [r.getMessage() for r in caplog.records if r.name == bs.logger.name]
    assert len(warnings) == 2 and all("unchecked:invalid_threshold" in w for w in warnings)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=bs.logger.name):
        bs.capture_policy(cfg(True, 0.15))
        bs.capture_policy(cfg(False, 1.5))  # off: the threshold is never used, no noise
    assert [r for r in caplog.records if r.name == bs.logger.name] == []


def test_budget_exceeded_propagates():
    with pytest.raises(BudgetExceeded):
        _check(_spine(), BudgetExceeded("run over budget"))
    with pytest.raises(BudgetExceeded):
        _check(BudgetExceeded("run over budget"), _spine())
    with pytest.raises(BudgetExceeded):
        _check(_spine(), None, table={"other": BudgetExceeded("run over budget")})
    # PipelineCancelled is a BaseException: it passes through untouched
    with pytest.raises(po.PipelineCancelled):
        _check(_spine(), po.PipelineCancelled("cancelled"))


def test_other_errors_unchecked():
    result, *_ = _check(_spine(), RuntimeError("provider 500"))
    assert result["status"] == "unchecked:error:RuntimeError" and result["calls"] == 2
    assert result["cross"] is None and result["within"] is None
    control_fail, *_ = _check(ValueError("bad json"), _spine())
    assert control_fail["status"] == "unchecked:error:ValueError" and control_fail["calls"] == 1
    unreadable, *_ = _check({}, _spine())
    assert unreadable["status"] == "unchecked:unreadable_draw:control"
    review = _spine((0.3, 0.5, 0.2))
    review["scenarios"][0]["probability"] = "about a third"
    needs_review, *_ = _check(_spine(), review)
    assert needs_review["status"] == "unchecked:unreadable_draw:secondary"
    assert bs.unchecked_artifact("error:KeyError")["status"] == "unchecked:error:KeyError"


@pytest.mark.parametrize("threshold", [None, float("nan"), 0, -0.1, 1.5, "abc"])
def test_invalid_threshold_makes_no_llm_call(threshold):
    # An unusable pinned threshold could never classify the draws: the check stops before
    # building a secondary client or paying for either spine draw.
    result, _primary, factory, log = _check(_spine(), _spine(), max_abs_delta=threshold)
    assert result["status"] == "unchecked:invalid_threshold"
    assert (result["calls"], log, factory.asked) == (0, [], [])
    assert result["cross"] is None and result["within"] is None


def _check_served(spine_served_by):
    log = []
    primary = _ScriptedLLM([_spine()], log=log)
    factory = _Factory({"other": ("o-1", [_spine()])}, log)
    result = bs.run_spine_backbone_check(
        follow_prompt="F", primary_spine=_spine(), primary_llm=primary, providers=["other"],
        client_factory=factory, max_tokens=100, spine_served_by=spine_served_by)
    return result, factory, log


def test_fallback_served_spine_is_unchecked():
    # Any spine call served by LLM_FALLBACK_PROVIDER (the first draw, a K>1 follow draw, the
    # REPORT-1 retry) makes ``within`` a cross-backbone comparison: no verdict and no call.
    for served in (["fallback"], ["primary", "fallback"], ["fallback", "primary"]):
        result, factory, log = _check_served(served)
        assert result["status"] == "unchecked:spine_served_by_fallback"
        assert (result["calls"], log, factory.asked) == (0, [], [])
        assert result["providers"]["primary"]["spine_served_by"] == served
        assert result["cross"] is None and result["within"] is None
    # served by the primary, replayed from the cache, or not reported: compared as usual
    for served in (["primary"], ["primary", "cache"], [None], []):
        result, factory, log = _check_served(served)
        assert result["status"] == "stable" and result["calls"] == 2
        assert result["providers"]["primary"]["spine_served_by"] == served
    observed = ["primary"]
    result, *_ = _check_served(observed)
    observed.append("fallback")  # the record keeps its own copy
    assert result["providers"]["primary"]["spine_served_by"] == ["primary"]


def test_spine_call_observer_delegates_and_records_who_served():
    class _Served(FakeLLMClient):
        """FakeLLMClient whose calls report who served them (None = no metadata)."""

        def __init__(self, served, **kwargs):
            super().__init__(**kwargs)
            self.served, self._meta = list(served), None

        def _stamp(self):
            who = self.served.pop(0)
            self._meta = None if who is None else {"served_by": who}

        def chat(self, messages, **kwargs):
            reply = super().chat(messages, **kwargs)
            self._stamp()
            return reply

        def chat_json(self, messages, **kwargs):
            reply = super().chat_json(messages, **kwargs)
            self._stamp()
            return reply

        def last_call_meta(self):
            return self._meta

    llm = _Served(["primary", "fallback", None], json_responses=[{"a": 1}, {"b": 2}],
                  responses=["text"], provider="minimax", model="m-1")
    observer = bs.SpineCallObserver(llm)
    assert (observer.provider, observer.model) == ("minimax", "m-1")  # attributes delegated
    msgs = [{"role": "user", "content": "x"}]
    assert observer.chat_json(messages=msgs, temperature=0.2, max_tokens=9) == {"a": 1}
    assert observer.chat(msgs) == "text"
    assert observer.chat_json(msgs) == {"b": 2}
    assert observer.served_by == ["primary", "fallback", None]
    # the wrapped client received exactly these calls, arguments unchanged
    assert [c["kind"] for c in llm.calls] == ["chat_json", "chat", "chat_json"]
    assert (llm.calls[0]["messages"], llm.calls[0]["temperature"],
            llm.calls[0]["max_tokens"]) == (msgs, 0.2, 9)

    class _Broken(FakeLLMClient):
        def chat_json(self, messages, **kwargs):
            raise RuntimeError("provider down")

    failing = bs.SpineCallObserver(_Broken())
    with pytest.raises(RuntimeError, match="provider down"):
        failing.chat_json(msgs)
    assert failing.served_by == []  # a call that never completed was served by nobody
    # without a wrapped client an attribute is plainly missing (no __getattr__ recursion)
    assert not hasattr(bs.SpineCallObserver.__new__(bs.SpineCallObserver), "model")


def test_throttled_provider_makes_no_call(monkeypatch):
    # The control shares the primary provider's process-wide 422/429 breaker: while it holds a
    # streak or a cooldown the check stays out of it entirely.
    monkeypatch.setattr(lc, "_CB_STATE", {})
    for state in ({"consec": 1.0}, {"consec429": 2.0},
                  {"consec": 0.0, "consec429": 0.0, "tripped_until": time.monotonic() + 60}):
        lc._CB_STATE["primary"] = dict(state)
        assert lc.circuit_breaker_quiet("Primary") is False
        result, _primary, factory, log = _check(_spine(), _spine())
        assert result["status"] == "unchecked:primary_throttled"
        assert (result["calls"], log, factory.asked) == (0, [], [])
        assert result["providers"]["primary"]["provider"] == "primary"
    # streaks reset by a success and the cooldown over: quiet again
    lc._CB_STATE["primary"] = {"consec": 0.0, "consec429": 0.0,
                               "tripped_until": time.monotonic() - 1}
    assert lc.circuit_breaker_quiet("primary") is True and lc.circuit_breaker_quiet("") is True
    # a secondary candidate whose own breaker is building toward a trip is skipped
    lc._CB_STATE["other"] = {"consec429": 1.0}
    table = {"other": ("o-1", [_spine()]), "third": ("t-1", [_spine()])}
    result, _primary, factory, log = _check(_spine(), None, providers=("other", "third"),
                                            table=table)
    assert result["skipped"] == [{"provider": "other", "reason": "throttled"}]
    assert result["providers"]["secondary"]["provider"] == "third"
    assert [c["provider"] for c in log] == ["primary", "third"]
    assert result["status"] == "stable"


def test_same_served_model_helper():
    def pair(a, b):
        return bs._same_served_model({"served_model": a}, {"served_model": b})

    assert pair("Model-X ", "model-x") is True
    assert pair("model-x", "model-y") is False
    for a, b in ((None, None), ("", ""), ("model-x", None), (None, "model-x")):
        assert pair(a, b) is False  # nothing reported on a side: no evidence either way


# ------------------------------------------------------ real LLMClient: cache bypass
PRIMARY, PRIMARY_MODEL, SECONDARY = "minimax", "MiniMax-M3", "deepseek"


def _resp(content, served_model):
    message = SimpleNamespace(content=content, tool_calls=[])
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                           usage=None, model=served_model)


class _Transport:
    """A fake OpenAI client serving one JSON reply forever (reporting ``served:<requested
    model>`` as the served model); records request kwargs."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _resp(self.reply, f"served:{kwargs.get('model')}")


@pytest.fixture
def real_clients(monkeypatch):
    transports = {}

    def build(provider, api_key, base_url):
        return transports.setdefault(provider, _Transport(json.dumps(_spine())))

    monkeypatch.setattr(lc.LLMClient, "_build_openai_client", staticmethod(build))
    for name in ("LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL", "LLM_FALLBACK_BASE_URL",
                 "LLM_FALLBACK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "LLM_PROVIDER": PRIMARY, "LLM_MODEL_NAME": PRIMARY_MODEL, "LLM_API_KEY": "sk-primary",
        "LLM_BASE_URL": "http://127.0.0.1:1/v1", "LLM_CACHE_ENABLED": True,
        "LLM_TRANSPORT_STRICT": True, "LLM_TELEMETRY_ENABLED": True,
        "LLM_RUN_BUDGET_TOKENS": 0, "LLM_RUN_BUDGET_USD": 0.0,
        "LLM_TIERED_ROUTING": True, "LLM_STRONG_MODEL": "primary-strong",
        "LLM_FAST_MODEL": "primary-fast", "LLM_FAST_PROVIDER": None,
        "LLM_FAST_BASE_URL": None, "LLM_FAST_API_KEY": None,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None
    yield transports
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None


def test_controls_bypass_cache(real_clients):
    transports = real_clients
    primary = lc.LLMClient()
    follow = [{"role": "user", "content": "FOLLOW PROMPT"}]
    # A same-prompt primary draw (e.g. a K>1 self-consistency draw) is already cached.
    primary.chat_json(messages=follow, temperature=0.2, max_tokens=6144)
    assert len(transports[PRIMARY].calls) == 1
    cached = dict(tel.LLMCache._store)
    assert len(cached) == 1

    def factory(name):
        return lc.LLMClient(provider=name, api_key="sk-2", base_url="http://127.0.0.1:2/v1",
                            model="deepseek-chat")

    results = [bs.run_spine_backbone_check(
        follow_prompt="FOLLOW PROMPT", primary_spine=_spine(), primary_llm=primary,
        providers=[SECONDARY], client_factory=factory, max_tokens=6144) for _ in range(2)]

    # Cache enabled, identical prompt twice: every control and secondary draw is a real call,
    # and nothing is read from or written to the cache.
    assert len(transports[PRIMARY].calls) == 3
    assert len(transports[SECONDARY].calls) == 2
    assert tel.LLMCache._store == cached
    # The control is served the model the primary spine draw was (the strong tier alias), the
    # secondary its own model.
    assert {c["model"] for c in transports[PRIMARY].calls} == {"primary-strong"}
    assert {c["model"] for c in transports[SECONDARY].calls} == {"deepseek-chat"}
    assert [r["status"] for r in results] == ["stable", "stable"]
    # served_model is what the provider reported serving each backbone's draw
    assert results[0]["providers"] == {
        "primary": {"provider": PRIMARY, "model": "primary-strong",
                    "served_model": "served:primary-strong", "spine_served_by": None},
        "secondary": {"provider": SECONDARY, "model": "deepseek-chat",
                      "served_model": "served:deepseek-chat"}}
    assert (primary.use_cache, primary._pinned) == (True, False)


def test_same_served_model_is_unchecked(real_clients):
    """Two provider labels a proxy routes to one model are not a cross-backbone pair: both
    providers report the same served model, so the check refuses a verdict (the metrics are
    kept for the record)."""
    transports = real_clients
    primary = lc.LLMClient()

    def factory(name):
        return lc.LLMClient(provider=name, api_key="sk-2", base_url="http://127.0.0.1:2/v1",
                            model="primary-strong")

    result = bs.run_spine_backbone_check(
        follow_prompt="FOLLOW PROMPT", primary_spine=_spine(), primary_llm=primary,
        providers=[SECONDARY], client_factory=factory, max_tokens=6144)
    assert result["status"] == "unchecked:same_served_model"
    assert (result["providers"]["primary"]["served_model"],
            result["providers"]["secondary"]["served_model"]) == (
        "served:primary-strong", "served:primary-strong")
    assert result["calls"] == 2
    assert len(transports[PRIMARY].calls) == len(transports[SECONDARY].calls) == 1
    # what the metrics alone would have claimed
    assert bs.classify(result["cross"], result["within"], 0.15) == "stable"


def test_observer_sees_a_fallback_served_spine_draw(real_clients, monkeypatch):
    """The real LLMClient failover: the unpinned primary's spine draw is served by
    LLM_FALLBACK_PROVIDER; the observer records it and the check makes no call."""
    transports = real_clients
    for name, value in {"LLM_FALLBACK_PROVIDER": SECONDARY, "LLM_FALLBACK_MODEL": "deepseek-chat",
                        "LLM_FALLBACK_BASE_URL": "http://127.0.0.1:3/v1",
                        "LLM_FALLBACK_API_KEY": "sk-fallback"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(lc, "_FB_OPENAI_CLIENTS", {})
    monkeypatch.setattr(lc, "_FB_AUTH_UNAVAILABLE_UNTIL", {})
    monkeypatch.setattr(lc, "_cb_tripped", lambda provider: provider == PRIMARY)

    primary = lc.LLMClient()
    observer = bs.SpineCallObserver(primary)
    spine = fe.derive_forecast_spine(observer, central_question="Will adoption accelerate?")
    assert spine.get("scenarios")
    assert observer.served_by == ["fallback"]
    assert transports[PRIMARY].calls == [] and len(transports[SECONDARY].calls) == 1

    asked = []
    result = bs.run_spine_backbone_check(
        follow_prompt="FOLLOW PROMPT", primary_spine=spine, primary_llm=primary,
        providers=["codex-cli"], client_factory=lambda name: asked.append(name),
        max_tokens=6144, spine_served_by=observer.served_by)
    assert result["status"] == "unchecked:spine_served_by_fallback" and result["calls"] == 0
    assert result["providers"]["primary"]["spine_served_by"] == ["fallback"]
    assert asked == [] and transports[PRIMARY].calls == []
    assert len(transports[SECONDARY].calls) == 1


def test_cli_backbones_record_the_model_they_are_asked_for(real_clients, monkeypatch):
    """A claude-cli / codex-cli client from the real _build_ensemble_client inherits
    LLM_MODEL_NAME (MiniMax-M3 under this minimax primary), which the CLI never receives: the
    recorded identity is the model actually requested (None = the CLI's account default), and
    backbones are compared on it. No draw is made."""
    primary = lc.LLMClient()
    ident = bs._identity(primary, bs._spine_model(primary))
    assert ident == {"provider": PRIMARY, "model": "primary-strong", "served_model": None}
    for name in ("claude-cli", "codex-cli"):
        skipped = []
        client, secondary = bs._pick_secondary([name], ident, fe._build_ensemble_client, skipped)
        assert client.model == PRIMARY_MODEL and lc.claude_cli_model_arg(client.model) is None
        assert secondary == {"provider": name, "model": None, "served_model": None}
        assert skipped == [] and (client._pinned, client.use_cache) == (True, False)

    # A claude-cli primary that inherited the non-claude name also runs the CLI default, so a
    # claude-cli candidate is the same backbone (skipped) and codex-cli is distinct.
    cli_primary = lc.LLMClient(provider="claude-cli")
    cli_ident = bs._identity(cli_primary, bs._spine_model(cli_primary))
    assert cli_ident == {"provider": "claude-cli", "model": None, "served_model": None}
    skipped = []
    client, secondary = bs._pick_secondary(["claude-cli", "codex-cli"], cli_ident,
                                           fe._build_ensemble_client, skipped)
    assert skipped == [{"provider": "claude-cli", "reason": "same_as_primary"}]
    assert secondary == {"provider": "codex-cli", "model": None, "served_model": None}

    # A claude id does reach the Claude CLI and is recorded as such.
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "claude-opus-4-8", raising=False)
    _client, named = bs._pick_secondary(["claude-cli"], ident, fe._build_ensemble_client, [])
    assert named == {"provider": "claude-cli", "model": "claude-opus-4-8", "served_model": None}

    # Through the check: the record never names the inherited model, while the control keeps
    # the client's own model (the CLI drops it exactly as it did for the spine draw).
    log = []
    scripted = _ScriptedLLM([_spine()], provider="claude-cli", model=PRIMARY_MODEL, log=log)
    factory = _Factory({"claude-cli": (PRIMARY_MODEL, []), "other": ("o-1", [_spine()])}, log)
    result = bs.run_spine_backbone_check(
        follow_prompt="F", primary_spine=_spine(), primary_llm=scripted,
        providers=["claude-cli", "other"], client_factory=factory, max_tokens=100)
    assert result["providers"]["primary"] == {"provider": "claude-cli", "model": None,
                                              "served_model": None, "spine_served_by": None}
    assert result["skipped"] == [{"provider": "claude-cli", "reason": "same_as_primary"}]
    assert [(c["provider"], c["model"]) for c in log] == [
        ("claude-cli", PRIMARY_MODEL), ("other", "o-1")]
    assert result["status"] == "stable"


def test_ensemble_client_never_sends_the_primary_key_elsewhere(real_clients, monkeypatch):
    """A keyless secondary provider fails to construct instead of inheriting the primary's
    LLM_API_KEY (LLMClient's fallback) and sending it to that provider's default_base."""
    for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        fe._build_ensemble_client(SECONDARY)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        fe._build_ensemble_client("openai")

    # the check records the keyless candidate as unusable and takes the next one
    primary = lc.LLMClient()
    skipped = []
    _client, secondary = bs._pick_secondary(
        [SECONDARY, "codex-cli"], bs._identity(primary, bs._spine_model(primary)),
        fe._build_ensemble_client, skipped)
    assert skipped == [{"provider": SECONDARY, "reason": "construct_failed:ValueError"}]
    assert secondary["provider"] == "codex-cli"

    # a configured key is the provider's own; the primary's own name keeps LLM_API_KEY
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    deepseek = fe._build_ensemble_client(SECONDARY)
    assert (deepseek.api_key, deepseek.base_url) == (
        "sk-deepseek", Config.PROVIDER_META[SECONDARY]["default_base"])

    # The primary's own name reuses LLM_API_KEY only on the primary's own endpoint (never on
    # the provider's default_base), also when the settings menu mirrored it into key_env; a
    # distinct key of the provider's own goes to the provider's default_base.
    own = fe._build_ensemble_client(PRIMARY)
    assert (own.api_key, own.base_url) == ("sk-primary", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-primary")
    assert fe._build_ensemble_client(PRIMARY).base_url == "http://127.0.0.1:1/v1"
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-minimax-own")
    distinct = fe._build_ensemble_client(PRIMARY)
    assert (distinct.api_key, distinct.base_url) == (
        "sk-minimax-own", Config.PROVIDER_META[PRIMARY]["default_base"])


def test_primary_key_behind_a_proxy_stays_on_the_proxy(real_clients, monkeypatch):
    """An 'openai' primary behind a proxy with OPENAI_API_KEY unset: listing 'openai' as a
    candidate must never build a client for api.openai.com carrying the proxy's key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name, value in {"LLM_PROVIDER": "openai", "LLM_BASE_URL": "http://my-proxy.example/v1",
                        "LLM_API_KEY": "sk-proxy", "LLM_MODEL_NAME": "gpt-4o"}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    client = fe._build_ensemble_client("openai")
    assert (client.api_key, client.base_url, client.model) == (
        "sk-proxy", "http://my-proxy.example/v1", "gpt-4o-mini")
    # the check still takes it as a distinct backbone (another model), reached via the proxy
    primary = lc.LLMClient()
    skipped = []
    picked, ident = bs._pick_secondary(["openai"], bs._identity(primary, bs._spine_model(primary)),
                                       fe._build_ensemble_client, skipped)
    assert (picked.api_key, picked.base_url) == ("sk-proxy", "http://my-proxy.example/v1")
    assert ident["model"] == "gpt-4o-mini" and skipped == []
    # a key of the provider's own goes to the provider's own endpoint
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    own = fe._build_ensemble_client("openai")
    assert (own.api_key, own.base_url) == ("sk-openai", Config.PROVIDER_META["openai"]["default_base"])


# =============================================================== 4. report level
class _RouterLLM(_ScriptedLLM):
    """Primary report LLM: the follow prompt (the control) gets ``control``; any other prompt
    (the spine draw) gets ``spine``."""

    def __init__(self, spine, control, log):
        super().__init__([], log=log)
        self._spine_reply, self._control_reply = spine, control

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        content = messages[-1]["content"]
        self.replies = [self._control_reply if _FOLLOW_MARKER in content else self._spine_reply]
        return super().chat_json(messages, temperature=temperature, max_tokens=max_tokens,
                                 tier=tier, **kwargs)


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


_MOVED = (0.3, 0.45, 0.15, 0.1)
_MOVED_NAMES = _NAMES + ("Residual",)


def _critique_stub(forecast, llm, language=""):
    """A pre-prose critique that moves every probability and adds a residual scenario."""
    return dict(forecast, scenarios=_rows(list(_MOVED), _MOVED_NAMES), critiqued=True)


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    for name, value in {
        "REPORT_FORECAST_SELF_CRITIQUE": True, "REPORT_CRITIQUE_BEFORE_PROSE": True,
        "REPORT_PREMORTEM": False, "REPORT_SPINE_SELFCONSISTENCY_K": 1,
        "FORECAST_EMIT_BINARY": False, "REPORT_PUBLISH_GATE": False,
        "REPORT_REPAIR_PASSES": False, "REPORT_FORECAST_LEDGER": False,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(fe, "self_critique_forecast", _critique_stub)
    monkeypatch.setattr(fe, "premortem_forecast", lambda forecast, llm, language="": forecast)
    tel.set_stage("report")
    yield tmp_path
    tel.set_stage(None)


def _secondary_factory(monkeypatch, reply, log):
    built = []

    def factory(name):
        client = _ScriptedLLM([reply], provider=name, model=f"{name}-1", log=log)
        built.append(name)
        return client

    monkeypatch.setattr(fe, "_build_ensemble_client", factory)
    return built


def _run_report(tmp_path, report_id, *, policy="absent", control=None, spine=None):
    """Spine + finalize for one report; returns (agent, log, forecast.json text)."""
    log = []
    spine = spine or _spine()
    llm = _RouterLLM(spine, control if control is not None else spine, log)
    (tmp_path / "reports" / report_id).mkdir(parents=True)
    agent = _agent(llm)
    if policy != "absent":
        agent.backbone_check_policy = policy
    agent._derive_and_pin_forecast_spine(report_id)
    assert agent._forecast_spine and agent._forecast_spine.get("scenarios")
    agent._finalize_structured_forecast(report_id, "# T\n\nBody text.")
    with open(os.path.join(str(tmp_path), "reports", report_id, "forecast.json"),
              encoding="utf-8") as handle:
        return agent, log, handle.read()


_ENABLED = {"enabled": True, "providers": ["other"], "max_abs_delta": 0.15}


def test_disabled_policy_no_quality_key_and_identical_prompts(report_env, monkeypatch):
    # The shipped defaults: off, no providers, 0.15; the admission pin records exactly that.
    assert (Config.BACKBONE_CHECK_ENABLED, Config.BACKBONE_CHECK_PROVIDERS,
            Config.BACKBONE_CHECK_MAX_ABS_DELTA) == (False, "", 0.15)
    assert po.capture_safety_policy_v1("admission")["backbone_check"] == {
        "enabled": False, "providers": [], "max_abs_delta": 0.15}

    def no_factory(name):
        raise AssertionError("a disabled check must not build a secondary client")

    monkeypatch.setattr(fe, "_build_ensemble_client", no_factory)
    _agent0, base_log, base_json = _run_report(report_env, "report_base")
    assert "backbone_sensitivity" not in (json.loads(base_json).get("quality") or {})
    assert [c["prompt"] for c in base_log if _FOLLOW_MARKER in c["prompt"]] == []
    for i, policy in enumerate((None, dict(_ENABLED, enabled=False), {"enabled": "true"},
                                {"enabled": 1, "providers": ["other"]}, "junk")):
        agent, log, text = _run_report(report_env, f"report_off_{i}", policy=policy)
        assert text == base_json  # forecast.json byte-identical
        assert [(c["prompt"], c["temperature"], c["max_tokens"]) for c in log] == [
            (c["prompt"], c["temperature"], c["max_tokens"]) for c in base_log]
        assert agent._backbone_sensitivity is None


def test_enabled_records_block_probabilities_unchanged(report_env, monkeypatch):
    sec_log = []
    built = _secondary_factory(monkeypatch, _spine((0.3, 0.5, 0.2)), sec_log)
    off_agent, off_log, off_json = _run_report(report_env, "report_check_off")
    assert built == []
    agent, log, on_json = _run_report(report_env, "report_check_on", policy=dict(_ENABLED))
    assert built == ["other"]

    off, on = json.loads(off_json), json.loads(on_json)
    record = on["quality"].pop("backbone_sensitivity")
    if not on["quality"]:
        on.pop("quality")
    # published forecast (probabilities, intervals, everything else) equals the no-check run
    assert on == off
    assert [s["probability"] for s in on["scenarios"]] == list(_MOVED)  # the critiqued spine

    assert record["schema"] == "backbone-sensitivity/v1" and record["calls"] == 2
    assert record["status"] == "backbone_sensitive"
    assert record["providers"]["secondary"] == {"provider": "other", "model": "other-1",
                                                "served_model": None}
    # the spine derivation went through the observer: one call, whose server the fake does not
    # report
    assert record["providers"]["primary"]["spine_served_by"] == [None]
    assert record["within_basis"] == bs.WITHIN_BASIS
    assert record["cross"]["leader_agree"] is False
    # within = pre-critique spine vs control: zero, although the critique moved every
    # probability of the published spine and added a scenario
    assert record["within"]["tv"] == 0.0 and record["within"]["matched"] == 3
    assert agent._backbone_sensitivity == record

    # the control reused the spine prompt byte-for-byte, pinned the PRE-critique scenario
    # names, ran on the primary backbone and was metered under 'backbone_check'
    spine_prompt = off_log[0]["prompt"]
    control = [c for c in log if _FOLLOW_MARKER in c["prompt"]]
    assert len(control) == 1 and len(sec_log) == 1
    assert control[0]["prompt"] == fe.spine_follow_prompt(spine_prompt, list(_NAMES))
    assert sec_log[0]["prompt"] == control[0]["prompt"]
    assert (control[0]["pinned"], control[0]["use_cache"]) == (True, False)
    assert {control[0]["stage"], sec_log[0]["stage"]} == {"backbone_check"}
    assert tel.get_run_context()[1] == "report"  # stage restored
    # the primary's own calls are exactly the no-check run's
    assert ([c["prompt"] for c in log if _FOLLOW_MARKER not in c["prompt"]]
            == [c["prompt"] for c in off_log])
    assert off_agent._forecast_spine["scenarios"] == agent._forecast_spine["scenarios"]


class _ServedRouterLLM(_RouterLLM):
    """_RouterLLM whose calls report who served them (scripted per call, then 'primary')."""

    def __init__(self, spine, control, log, served):
        super().__init__(spine, control, log)
        self.served, self._meta = list(served), None

    def chat_json(self, messages, **kwargs):
        reply = super().chat_json(messages, **kwargs)
        self._meta = {"served_by": self.served.pop(0) if self.served else "primary"}
        return reply

    def last_call_meta(self):
        return self._meta


def test_report_fallback_served_spine_recorded_unchecked(report_env, monkeypatch):
    built = _secondary_factory(monkeypatch, _spine(), [])
    _off_agent, off_log, off_json = _run_report(report_env, "report_fb_off")
    # K=2: only the FIRST spine draw failed over; the last call's metadata alone says 'primary'
    for k, served in ((1, ["fallback"]), (2, ["fallback", "primary"])):
        monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", k, raising=False)
        report_id = f"report_fb_k{k}"
        (report_env / "reports" / report_id).mkdir(parents=True)
        log = []
        agent = _agent(_ServedRouterLLM(_spine(), _spine(), log, served))
        agent.backbone_check_policy = dict(_ENABLED)
        agent._derive_and_pin_forecast_spine(report_id)
        agent._finalize_structured_forecast(report_id, "# T\n\nBody text.")
        forecast = json.loads(
            (report_env / "reports" / report_id / "forecast.json").read_text(encoding="utf-8"))
        record = forecast["quality"].pop("backbone_sensitivity")
        assert record["status"] == "unchecked:spine_served_by_fallback" and record["calls"] == 0
        assert record["providers"]["primary"]["spine_served_by"] == served
        # no control draw: the only follow-prompt call is the spine's own K=2 draw
        assert len([c for c in log if _FOLLOW_MARKER in c["prompt"]]) == k - 1
        assert [s["probability"] for s in forecast["scenarios"]] == list(_MOVED)
        if k == 1:
            if not forecast["quality"]:
                forecast.pop("quality")
            assert forecast == json.loads(off_json)
            assert [c["prompt"] for c in log] == [c["prompt"] for c in off_log]
    assert built == []  # no secondary client was ever built


def test_report_budget_exceeded_propagates_and_keeps_spine(report_env, monkeypatch):
    _secondary_factory(monkeypatch, BudgetExceeded("run over budget"), [])
    log = []
    llm = _RouterLLM(_spine(), _spine(), log)
    (report_env / "reports" / "report_budget").mkdir(parents=True)
    agent = _agent(llm)
    agent.backbone_check_policy = dict(_ENABLED)
    with pytest.raises(BudgetExceeded):
        agent._derive_and_pin_forecast_spine("report_budget")
    # the published spine survived (the check runs outside the spine's try/except)
    assert [s["probability"] for s in agent._forecast_spine["scenarios"]] == list(_MOVED)
    assert agent._forecast_spine_block
    assert agent._backbone_sensitivity is None
    assert tel.get_run_context()[1] == "report"


def test_report_other_errors_recorded_unchecked(report_env, monkeypatch):
    _secondary_factory(monkeypatch, _spine(), [])

    def broken(user, names):
        raise KeyError("follow")

    monkeypatch.setattr(fe, "spine_follow_prompt", broken)
    agent, _log, text = _run_report(report_env, "report_error", policy=dict(_ENABLED))
    record = json.loads(text)["quality"]["backbone_sensitivity"]
    assert record["status"] == "unchecked:error:KeyError" and record["calls"] == 0
    assert record["note"] == "shadow diagnostic; probabilities unchanged"
    assert [s["probability"] for s in json.loads(text)["scenarios"]] == list(_MOVED)
    assert tel.get_run_context()[1] == "report"


def test_enabled_without_a_spine_records_no_spine(report_env, monkeypatch):
    # The spine derivation produced no scenarios (the post-prose extraction publishes instead):
    # an opted-in run says so, a run that never opted in still has no key at all.
    built = _secondary_factory(monkeypatch, _spine(), [])
    monkeypatch.setattr(fe, "derive_forecast_spine", lambda llm, **kwargs: None)
    monkeypatch.setattr(fe, "extract_structured_forecast", lambda md, llm, **kwargs: _spine())
    published = {}
    for label, policy in (("on", dict(_ENABLED)), ("off", None)):
        report_id = f"report_no_spine_{label}"
        (report_env / "reports" / report_id).mkdir(parents=True)
        log = []
        agent = _agent(_RouterLLM(_spine(), _spine(), log))
        agent.backbone_check_policy = policy
        agent._derive_and_pin_forecast_spine(report_id)
        assert agent._forecast_spine is None and agent._backbone_sensitivity is None
        agent._finalize_structured_forecast(report_id, "# T\n\nBody text.")
        published[label] = json.loads(
            (report_env / "reports" / report_id / "forecast.json").read_text(encoding="utf-8"))
        assert [c for c in log if _FOLLOW_MARKER in c["prompt"]] == []
    assert built == []  # nothing to check: no secondary client, no draw
    assert "backbone_sensitivity" not in (published["off"].get("quality") or {})
    record = published["on"]["quality"].pop("backbone_sensitivity")
    assert (record["status"], record["calls"], record["note"]) == (
        "unchecked:no_spine", 0, "shadow diagnostic; probabilities unchanged")
    if not published["on"]["quality"]:
        published["on"].pop("quality")
    assert published["on"] == published["off"]


def test_only_the_main_report_stage_sets_the_policy():
    """Seed reports, model_comparison and the API path never run the check: the only
    assignment outside ReportAgent's None default is the main report stage in _run."""
    pattern = re.compile(r"\.backbone_check_policy\s*(?::[^=\n]*)?=(?!=)")
    hits = {}
    for root in ("app", "scripts"):
        for path in sorted((_BACKEND / root).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            found = pattern.findall(text)
            if found:
                hits[path.relative_to(_BACKEND).as_posix()] = len(found)
    assert hits == {"app/services/pipeline_orchestrator.py": 1,
                    "app/services/report_agent.py": 1}
    assert ("self.backbone_check_policy: Optional[Dict[str, Any]] = None"
            in inspect.getsource(ReportAgent.__init__))
    assert ("agent.backbone_check_policy = self._backbone_check_policy(state)"
            in inspect.getsource(po.PipelineOrchestrator._run))
    for fn in (po.PipelineOrchestrator._run_one_seed, po.PipelineOrchestrator._generate_stage_report):
        assert "backbone_check" not in inspect.getsource(fn)


# =============================================================== 5. admission pin
@pytest.fixture
def pipelines(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))
    return tmp_path


def _settle(pipeline_id):
    thread = po.PipelineOrchestrator._threads.pop(pipeline_id, None)
    if thread is not None:
        thread.join(timeout=5)
    po.PipelineOrchestrator._cancel_events.pop(pipeline_id, None)


def _ambient(monkeypatch, enabled, providers="", delta=0.15):
    monkeypatch.setattr(Config, "BACKBONE_CHECK_ENABLED", enabled, raising=False)
    monkeypatch.setattr(Config, "BACKBONE_CHECK_PROVIDERS", providers, raising=False)
    monkeypatch.setattr(Config, "BACKBONE_CHECK_MAX_ABS_DELTA", delta, raising=False)


def _policy(pipeline_id):
    state = po.PipelineState.from_dict(po.PipelineManager.load(pipeline_id))
    return po.PipelineOrchestrator._backbone_check_policy(state)


def _resume(pipeline_id):
    po.PipelineManager.mark_failed(pipeline_id, "boom")
    po.PipelineOrchestrator.resume(pipeline_id)
    _settle(pipeline_id)


def test_pin_survives_config_change_on_resume(pipelines, monkeypatch):
    # opted in at admission -> stays on after the operator turns the knob off
    _ambient(monkeypatch, True, "DeepSeek, glm", 0.2)
    on = po.PipelineOrchestrator.start("Will X happen by 2030?", mode="full")
    _settle(on.pipeline_id)
    pinned = {"enabled": True, "providers": ["deepseek", "glm"], "max_abs_delta": 0.2}
    assert po.PipelineManager.load(on.pipeline_id)["options"]["safety_policy_v1"][
        "backbone_check"] == pinned
    _ambient(monkeypatch, False, "", 0.5)
    _resume(on.pipeline_id)
    assert _policy(on.pipeline_id) == pinned

    # admitted off -> stays off after the operator turns the knob on
    off = po.PipelineOrchestrator.start("Will Y happen by 2030?", mode="full")
    _settle(off.pipeline_id)
    _ambient(monkeypatch, True, "deepseek")
    _resume(off.pipeline_id)
    assert _policy(off.pipeline_id) is None

    # a pin captured before EVAL-11 (no backbone_check key) is kept, never re-captured
    legacy_pin = po.PipelineState.from_dict(po.PipelineManager.load(off.pipeline_id))
    legacy_pin.options["safety_policy_v1"].pop("backbone_check")
    po.PipelineManager.save(legacy_pin)
    _resume(off.pipeline_id)
    assert "backbone_check" not in po.PipelineManager.load(off.pipeline_id)["options"][
        "safety_policy_v1"]
    assert _policy(off.pipeline_id) is None

    # a run admitted before any safety pin: the legacy resume records the check disabled
    legacy = po.PipelineState.from_dict(po.PipelineManager.load(off.pipeline_id))
    legacy.pipeline_id = "pipe_eval11_legacy"
    legacy.options.pop("safety_policy_v1")
    po.PipelineManager.ensure_dirs(legacy.pipeline_id)
    po.PipelineManager.save(legacy)
    _resume(legacy.pipeline_id)
    policy = po.PipelineManager.load(legacy.pipeline_id)["options"]["safety_policy_v1"]
    assert policy["origin"] == "resume_reconstructed_safe"
    assert policy["backbone_check"] == {"enabled": False}
    assert _policy(legacy.pipeline_id) is None


def test_fork_pin_inherits_or_captures_at_fork_admission(monkeypatch):
    monkeypatch.setattr(Config, "FORK_INHERIT_SAFETY_POLICY", True, raising=False)
    _ambient(monkeypatch, True, "glm")
    base = po.capture_safety_policy_v1("admission")
    _ambient(monkeypatch, False)
    inherited = po.fork_safety_policy_v1({"safety_policy_v1": base})
    assert inherited["origin"] == "fork_inherited"
    assert inherited["backbone_check"] == {"enabled": True, "providers": ["glm"],
                                           "max_abs_delta": 0.15}
    _ambient(monkeypatch, True, "kimi")
    captured = po.fork_safety_policy_v1({})
    assert captured["origin"] == "fork_admission"
    assert captured["backbone_check"]["providers"] == ["kimi"]
    for origin in ("resume_reconstructed_safe", "unknown"):
        assert po.capture_safety_policy_v1(origin)["backbone_check"] == {"enabled": False}
    # the report agent's policy is read from the pin with no ambient fallback
    bare = po.PipelineState(pipeline_id="pipe_bare", prompt="q")
    assert po.PipelineOrchestrator._backbone_check_policy(bare) is None
    bare.options["safety_policy_v1"] = {"backbone_check": "junk"}
    assert po.PipelineOrchestrator._backbone_check_policy(bare) is None
