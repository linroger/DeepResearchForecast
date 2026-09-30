"""Shadow cross-backbone sensitivity check for the forecast spine (EVAL-11, P15).

The scenario spine is the object the ledger scores, so this check asks whether its
scenario distribution depends on which model produced it. It reuses the spine's
fixed-scenario follow prompt (the K>1 self-consistency prompt: the spine prompt plus the
pinned scenario names, re-estimate only) and makes two extra draws at the spine
temperature:

* a same-backbone control: a shallow copy of the primary client, pinned to the model the
  primary spine draw was served (its strong tier) and opted out of LLMCache, so it is a
  real, independent call and never a replay of a cached reply;
* one secondary-backbone draw: the first configured provider whose client constructs and
  whose (provider, model) differs from the primary's, also pinned and uncached.

``cross`` compares the control with the secondary (identical prompt, only the backbone
differs). ``within`` compares the published pre-critique spine with the control, both from
the primary backbone. It is not pure sampling noise: that spine was drawn on the free spine
prompt (no pinned names, possibly with the REPORT-1 retry note, and pooled over K draws when
REPORT_SPINE_SELFCONSISTENCY_K > 1), while the control is one draw on the fixed-name follow
prompt, so ``within`` bundles sampling noise with the free-vs-follow prompt difference (the
record carries this as ``within_basis``). A cross difference counts as backbone sensitivity
only while the within difference stays under the threshold; otherwise the primary backbone
does not even reproduce its own spine and the cross difference cannot be attributed to the
backbone.

A backbone's identity is its provider plus the model its requests name. A CLI subscription
provider can run a model the client never names: the Claude CLI is given ``--model`` only for
a claude id/alias (llm_client.claude_cli_model_arg), so a claude-cli client that inherited
another provider's LLM_MODEL_NAME runs the account default, and ``codex exec`` is never given
a model. Such a backbone is recorded with model None (never the inherited name), and each
identity also carries the ``served_model`` the provider reported for its draw, if any. When
the control and the secondary report the same served model, the two labels reached one model
(a proxy routing both to it) and the check records ``unchecked:same_served_model`` instead of a
cross-backbone verdict. A proxy that reports no served model, or reports the requested name
whatever it routes to, remains undetectable by this check.

The primary client is not pinned, so any spine draw may have failed over to
LLM_FALLBACK_PROVIDER (S9). The report agent hands the spine derivation a SpineCallObserver
that notes who served each spine call (``providers.primary.spine_served_by``). A spine any of
whose calls the fallback served is not a within-backbone baseline: the check records
``unchecked:spine_served_by_fallback`` and makes no call. A spine replayed from LLMCache
(``'cache'``) is compared as usual; an unpinned client stores a fallback-served reply under its
primary key, so which backbone originally produced a replayed spine is not known here.

The control, and a secondary, share their provider's process-wide 422/429 circuit breaker
with every other client of that provider (llm_client._cb_record_422 / _cb_record_429 count
failures, a success resets the streaks, and a trip sends that provider's later calls straight
to the fallback provider, or fails them, for the cooldown). So that the shadow check never
pushes a throttled provider over the trip, and thereby changes who serves the report's later
calls (sections, binary extraction), it makes no call while the primary provider's breaker
holds a streak or a cooldown (``unchecked:primary_throttled``) and skips a secondary candidate
whose breaker does (reason ``throttled``). Residual: a check call that fails on a quiet
breaker still adds its own failures to that provider's streak.

Shadow only (ADR 0002 decision 6): the artifact is recorded in forecast.quality and never
moves a probability, an interval, a rendered table or the publish gate.

Error contract: BudgetExceeded propagates (a run over budget must stop); the orchestrator's
PipelineCancelled is a BaseException and passes through ``except Exception`` untouched;
any other failure records ``unchecked:error:<Type>`` instead of breaking the report.
Everything except ``run_spine_backbone_check`` is pure and offline-testable.
"""

from __future__ import annotations

import copy
import logging
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils.llm_client import CLI_PROVIDERS, circuit_breaker_quiet, claude_cli_model_arg
from ..utils.probability_parse import PROB_REVIEW
from ..utils.telemetry import BudgetExceeded
from . import forecast_extractor as _fe
from .ensemble import _norm_name

logger = logging.getLogger(__name__)

SCHEMA = "backbone-sensitivity/v1"
NOTE = "shadow diagnostic; probabilities unchanged"
# What ``within`` compares (see the module docstring): not sampling noise alone.
WITHIN_BASIS = ("pre-critique spine (free spine prompt, pooled when K>1) vs one control draw "
                "on the fixed-name follow prompt: sampling noise plus the prompt difference")

STATUS_STABLE = "stable"
STATUS_BACKBONE_SENSITIVE = "backbone_sensitive"
STATUS_UNSTABLE_WITHIN = "unstable_within_backbone"
UNCHECKED = "unchecked"

DEFAULT_MAX_ABS_DELTA = 0.15
# The spine's own draw temperature (derive_forecast_spine's first draw).
SPINE_TEMPERATURE = 0.2
# Scenarios whose probabilities differ by at most this much share the lead.
_LEADER_TIE_EPS = 1e-9

# The pin recorded for an origin that must not capture the ambient opt-in.
DISABLED_POLICY: Dict[str, Any] = {"enabled": False}


def _as_float(value: Any) -> Optional[float]:
    """A finite float, or None (bools, non-numbers, NaN and infinities are rejected)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _threshold(value: Any) -> Optional[float]:
    """The comparison threshold as a float in (0, 1], or None when it is unusable."""
    number = _as_float(value)
    return number if number is not None and 0.0 < number <= 1.0 else None


def parse_providers(raw: Any) -> List[str]:
    """Provider names from a comma-separated string or a list: lower-cased, blanks dropped,
    duplicates removed, order kept."""
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
    names: List[str] = []
    for item in items:
        name = str(item or "").strip().lower()
        if name and name not in names:
            names.append(name)
    return names


def capture_policy(config: Any) -> Dict[str, Any]:
    """The admission-time ``backbone_check`` pin, snapshotted from the ambient Config.

    An opted-in pin whose threshold is outside (0, 1] (or NaN) is still recorded as given;
    the check then records ``unchecked:invalid_threshold`` without any LLM call, and the
    operator is warned here, at admission.
    """
    raw_delta = getattr(config, "BACKBONE_CHECK_MAX_ABS_DELTA", DEFAULT_MAX_ABS_DELTA)
    policy = {
        "enabled": bool(getattr(config, "BACKBONE_CHECK_ENABLED", False)),
        "providers": parse_providers(getattr(config, "BACKBONE_CHECK_PROVIDERS", "")),
        "max_abs_delta": _as_float(raw_delta),
    }
    if policy["enabled"] and _threshold(raw_delta) is None:
        logger.warning(
            f"BACKBONE_CHECK_MAX_ABS_DELTA={raw_delta!r} is not in (0, 1]: the backbone check "
            "of this run will record unchecked:invalid_threshold and make no LLM call")
    return policy


def enabled_policy(pin: Any) -> Optional[Dict[str, Any]]:
    """A pinned ``backbone_check`` value as the report agent's policy, or None (disabled).

    Only a dict with ``enabled`` exactly True is enabled. A missing, malformed or disabled
    pin stays disabled; the ambient Config is never consulted here.
    """
    if not isinstance(pin, dict) or pin.get("enabled") is not True:
        return None
    return {
        "enabled": True,
        "providers": parse_providers(pin.get("providers")),
        "max_abs_delta": pin.get("max_abs_delta"),
    }


# ------------------------------------------------------------------ pure metrics
def _scenario_probs(spine: Any) -> Dict[str, float]:
    """Normalized scenario name -> probability (first occurrence wins; unreadable rows skipped)."""
    probs: Dict[str, float] = {}
    rows = spine.get("scenarios") if isinstance(spine, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key = _norm_name(row.get("name"))
        prob = _as_float(row.get("probability"))
        if key and prob is not None and key not in probs:
            probs[key] = prob
    return probs


def _leaders(probs: Dict[str, float]) -> List[str]:
    """The scenario keys tied for the highest probability (empty for an empty spine)."""
    if not probs:
        return []
    top = max(probs.values())
    return [key for key, prob in probs.items() if top - prob <= _LEADER_TIE_EPS]


def scenario_agreement(a: Any, b: Any) -> Dict[str, Any]:
    """Agreement between two spines' scenario distributions, matched by normalized name.

    ``tv`` is the total-variation distance 0.5 * sum |pa - pb| over the union of names (a
    name missing on one side counts as probability 0 there). ``leader_agree`` is true when
    the two spines share a leading scenario (ties allowed). ``per_scenario_abs_delta`` and
    ``max_abs_delta`` are rounded to 4 places; ``matched`` counts names present on both
    sides and ``missing`` lists the names present on only one.
    """
    pa, pb = _scenario_probs(a), _scenario_probs(b)
    union = list(pa) + [key for key in pb if key not in pa]
    raw = {key: abs(pa.get(key, 0.0) - pb.get(key, 0.0)) for key in union}
    leaders_a, leaders_b = _leaders(pa), _leaders(pb)
    return {
        "tv": round(0.5 * sum(raw.values()), 4),
        "leader_agree": bool(set(leaders_a) & set(leaders_b)),
        "leaders": {"a": leaders_a, "b": leaders_b},
        "per_scenario_abs_delta": {key: round(delta, 4) for key, delta in raw.items()},
        "max_abs_delta": round(max(raw.values()), 4) if raw else 0.0,
        "matched": sum(1 for key in pa if key in pb),
        "missing": [key for key in union if not (key in pa and key in pb)],
    }


def _exceeds(agreement: Dict[str, Any], threshold: float) -> bool:
    """True when the leader differs or any scenario moved by at least ``threshold``."""
    if not agreement.get("leader_agree"):
        return True
    delta = _as_float(agreement.get("max_abs_delta"))
    return delta is None or delta >= threshold


def classify(cross: Any, within: Any, max_abs_delta: Any) -> str:
    """Status of one check from its cross- and within-backbone agreements.

    * ``unstable_within_backbone``: the same backbone already disagrees with itself (leader
      change or a scenario delta >= threshold), whatever the cross comparison shows;
    * ``backbone_sensitive``: the cross comparison exceeds the threshold while the within
      comparison does not;
    * ``stable``: neither does;
    * ``unchecked:<reason>``: the threshold is not in (0, 1], an agreement is missing, or an
      agreement matched no scenario name (nothing comparable).
    """
    threshold = _threshold(max_abs_delta)
    if threshold is None:
        return f"{UNCHECKED}:invalid_threshold"
    for label, agreement in (("cross", cross), ("within", within)):
        if not isinstance(agreement, dict):
            return f"{UNCHECKED}:missing:{label}"
        if not agreement.get("matched"):
            return f"{UNCHECKED}:no_matched_scenarios:{label}"
    if _exceeds(within, threshold):
        return STATUS_UNSTABLE_WITHIN
    if _exceeds(cross, threshold):
        return STATUS_BACKBONE_SENSITIVE
    return STATUS_STABLE


def artifact(status: str, *, primary: Optional[Dict[str, Any]] = None,
             secondary: Optional[Dict[str, Any]] = None,
             cross: Optional[Dict[str, Any]] = None, within: Optional[Dict[str, Any]] = None,
             calls: int = 0, threshold: Any = None,
             skipped: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """The ``forecast.quality.backbone_sensitivity`` record.

    ``calls`` counts spine draws attempted (a draw's JSON repair turn, if any, is not counted
    separately). ``threshold`` is the pinned BACKBONE_CHECK_MAX_ABS_DELTA the draws were
    classified against; ``cross.max_abs_delta`` / ``within.max_abs_delta`` are the observed
    maxima. Each of ``providers.primary`` / ``providers.secondary`` is {provider, model,
    served_model}: ``model`` is the model the backbone's requests name (None when a CLI
    subscription provider runs its account default) and ``served_model`` the model the
    provider reported serving that backbone's draw in this check (the control draw for the
    primary; None when it reports none or the draw did not complete). ``providers.primary``
    also carries ``spine_served_by``: who served each call of the spine derivation
    ('primary' | 'fallback' | 'cache', None when not reported), or None when not observed.
    """
    return {
        "schema": SCHEMA,
        "providers": {"primary": primary, "secondary": secondary},
        "status": status,
        "cross": cross,
        "within": within,
        "within_basis": WITHIN_BASIS,
        "calls": int(calls),
        "threshold": threshold,
        "skipped": list(skipped or []),
        "note": NOTE,
    }


def unchecked_artifact(reason: str) -> Dict[str, Any]:
    """An ``unchecked:<reason>`` record for a check that failed before any comparison."""
    return artifact(f"{UNCHECKED}:{reason}")


# ------------------------------------------------------------------ the check
def _provider(client: Any) -> str:
    return str(getattr(client, "provider", "") or "").lower()


def _requested_model(provider: str, model: Any) -> Optional[str]:
    """The model a request of ``provider`` names when its client's ``model`` is ``model``, or
    None when a CLI subscription provider runs its account default.

    An OpenAI-compatible request carries ``model``. The Claude CLI is given ``--model`` only
    for a claude id/alias (claude_cli_model_arg: e.g. a claude-cli client built by
    _build_ensemble_client inherits LLM_MODEL_NAME, which under a MiniMax primary is
    MiniMax-M3 and never reaches the CLI); ``codex exec`` is never given a model.
    """
    name = None if model is None else str(model)
    if provider == "claude-cli":
        return claude_cli_model_arg(name)
    if provider == "codex-cli":
        return None
    return name


def _identity(client: Any, model: Any) -> Dict[str, Any]:
    """A backbone's recorded identity: provider plus the model its requests name (see
    _requested_model). ``served_model`` is filled in after the backbone's draw."""
    provider = _provider(client)
    return {"provider": provider, "model": _requested_model(provider, model),
            "served_model": None}


def _spine_model(primary_llm: Any) -> Any:
    """The client model the primary spine draw ran with: the strong-tier resolution (the model
    a chat_json call without a tier resolves to, tier routing included).

    CLI subscription providers ignore the tier alias (the tier only affects metering there),
    so their model is the client's own ``model``.
    """
    resolve = getattr(primary_llm, "_model_for_tier", None)
    if callable(resolve) and _provider(primary_llm) not in CLI_PROVIDERS:
        return resolve("strong")
    return getattr(primary_llm, "model", None)


def _last_meta_field(client: Any, field: str) -> Optional[str]:
    """One non-empty string field of ``client``'s last-call metadata on this thread (INFRA-1
    last_call_meta), or None when the client reports none."""
    last_call_meta = getattr(client, "last_call_meta", None)
    try:
        meta = last_call_meta() if callable(last_call_meta) else None
    except Exception:  # noqa: BLE001 — metadata is best-effort; never fails the check
        return None
    value = meta.get(field) if isinstance(meta, dict) else None
    return value if isinstance(value, str) and value else None


def _served_model(client: Any) -> Optional[str]:
    """The model the provider reported serving ``client``'s last call, or None."""
    return _last_meta_field(client, "served_model")


def _same_served_model(primary: Dict[str, Any], secondary: Dict[str, Any]) -> bool:
    """True when both backbones reported serving the same model (case and spacing ignored):
    the two provider labels reached one model, so the draws are not a cross-backbone pair."""
    a, b = primary.get("served_model"), secondary.get("served_model")
    return bool(a and b) and a.strip().casefold() == b.strip().casefold()


class SpineCallObserver:
    """The primary client as the spine derivation of an opted-in run sees it.

    Every attribute and call is delegated unchanged to the wrapped client (same client, same
    prompts, same replies). After each completed ``chat`` / ``chat_json`` it appends who served
    the call (last_call_meta()['served_by']: 'primary', 'fallback' or 'cache'; None when the
    client reports none) to ``served_by``. The derivation can make several calls (the REPORT-1
    retry, the K>1 self-consistency draws, a JSON repair turn inside chat_json), and the primary
    client is not pinned, so any of them may have failed over to LLM_FALLBACK_PROVIDER.
    """

    def __init__(self, llm: Any) -> None:
        self._llm = llm
        self.served_by: List[Optional[str]] = []

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        reply = self._llm.chat(*args, **kwargs)
        self.served_by.append(_last_meta_field(self._llm, "served_by"))
        return reply

    def chat_json(self, *args: Any, **kwargs: Any) -> Any:
        reply = self._llm.chat_json(*args, **kwargs)
        self.served_by.append(_last_meta_field(self._llm, "served_by"))
        return reply

    def __getattr__(self, name: str) -> Any:
        if name == "_llm":  # not yet set: never recurse into __getattr__
            raise AttributeError(name)
        return getattr(self._llm, name)


def _control_client(primary_llm: Any, model: Any) -> Any:
    """A same-backbone control: the primary client pinned to the spine's model, uncached.

    Order matters: the model is resolved on the unpinned primary first (a pinned client's
    _model_for_tier returns its own ``model``), then the copy opts out of the cache and pins.
    """
    control = copy.copy(primary_llm)
    control.model = model
    control.use_cache = False
    control._pinned = True
    return control


def _pick_secondary(providers: List[str], primary: Dict[str, Any],
                    client_factory: Callable[[str], Any],
                    skipped: List[Dict[str, str]]) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """The first provider whose client constructs, differs from the primary backbone and whose
    circuit breaker is quiet (see the module docstring).

    Backbones are compared on their recorded identity (provider + requested model), so a CLI
    candidate is compared on the model it would actually be asked for, never on an inherited
    name it would not receive.
    """
    for name in providers:
        try:
            client = client_factory(name)
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 — an unusable candidate is skipped, not fatal
            skipped.append({"provider": name, "reason": f"construct_failed:{type(exc).__name__}"})
            continue
        ident = _identity(client, getattr(client, "model", None))
        if (ident["provider"], ident["model"]) == (primary["provider"], primary["model"]):
            skipped.append({"provider": name, "reason": "same_as_primary"})
            continue
        if not circuit_breaker_quiet(ident["provider"]):
            skipped.append({"provider": name, "reason": "throttled"})
            continue
        client._pinned = True
        client.use_cache = False
        return client, ident
    return None, None


def _readable(draw: Any) -> bool:
    return (isinstance(draw, dict) and bool(draw.get("scenarios"))
            and draw.get("probability_status") != PROB_REVIEW)


def run_spine_backbone_check(*, follow_prompt: str, primary_spine: Dict[str, Any],
                             primary_llm: Any, providers: Any,
                             client_factory: Callable[[str], Any], max_tokens: int,
                             max_abs_delta: Any = DEFAULT_MAX_ABS_DELTA,
                             spine_served_by: Optional[List[Optional[str]]] = None,
                             ) -> Dict[str, Any]:
    """Run the shadow check and return its artifact (see the module docstring).

    ``follow_prompt`` is the spine prompt with ``primary_spine``'s scenario names pinned
    (forecast_extractor.spine_follow_prompt); ``primary_spine`` is the within-backbone
    baseline (the spine before any critique); ``client_factory`` builds a client for a
    provider name (forecast_extractor._build_ensemble_client); ``spine_served_by`` is who
    served each call of the spine derivation (SpineCallObserver.served_by; None when not
    observed). An unusable threshold, a fallback-served spine, a throttled primary or no
    usable secondary backbone means no LLM call. BudgetExceeded propagates; other errors yield
    ``unchecked:error:<Type>``.
    """
    skipped: List[Dict[str, str]] = []
    primary: Optional[Dict[str, Any]] = None
    secondary: Optional[Dict[str, Any]] = None
    calls = 0

    def _record(status: str, **extra: Any) -> Dict[str, Any]:
        return artifact(status, primary=primary, secondary=secondary, calls=calls,
                        threshold=_as_float(max_abs_delta), skipped=skipped, **extra)

    # An unusable threshold could never classify the draws: fail before paying for them.
    if _threshold(max_abs_delta) is None:
        return _record(f"{UNCHECKED}:invalid_threshold")
    try:
        spine_model = _spine_model(primary_llm)
        primary = _identity(primary_llm, spine_model)
        primary["spine_served_by"] = None if spine_served_by is None else list(spine_served_by)
        # The fallback backbone drew (part of) the baseline: ``within`` would be cross-backbone.
        if "fallback" in (spine_served_by or ()):
            return _record(f"{UNCHECKED}:spine_served_by_fallback")
        if not circuit_breaker_quiet(primary["provider"]):
            return _record(f"{UNCHECKED}:primary_throttled")
        secondary_llm, secondary = _pick_secondary(
            parse_providers(providers), primary, client_factory, skipped)
        if secondary_llm is None:
            return _record(f"{UNCHECKED}:no_distinct_secondary")
        control = _control_client(primary_llm, spine_model)
        calls += 1
        control_draw = _fe._spine_draw(control, follow_prompt, SPINE_TEMPERATURE, max_tokens)
        primary["served_model"] = _served_model(control)
        calls += 1
        secondary_draw = _fe._spine_draw(secondary_llm, follow_prompt, SPINE_TEMPERATURE,
                                         max_tokens)
        secondary["served_model"] = _served_model(secondary_llm)
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 — shadow diagnostic: record, never break the report
        return _record(f"{UNCHECKED}:error:{type(exc).__name__}")
    for label, draw in (("control", control_draw), ("secondary", secondary_draw)):
        if not _readable(draw):
            return _record(f"{UNCHECKED}:unreadable_draw:{label}")
    cross = scenario_agreement(control_draw, secondary_draw)
    within = scenario_agreement(primary_spine, control_draw)
    if _same_served_model(primary, secondary):
        return _record(f"{UNCHECKED}:same_served_model", cross=cross, within=within)
    return _record(classify(cross, within, max_abs_delta), cross=cross, within=within)
