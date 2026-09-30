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
differs). ``within`` compares the pre-critique primary spine with the control (same
backbone, sampling noise only). A cross difference counts as backbone sensitivity only
while the within difference stays under the threshold; otherwise the backbone does not
even agree with itself and the cross difference cannot be attributed to it.

Shadow only (ADR 0002 decision 6): the artifact is recorded in forecast.quality and never
moves a probability, an interval, a rendered table or the publish gate. Known limit: a
proxy can route two provider labels to one model family, which a name comparison cannot
detect.

Error contract: BudgetExceeded propagates (a run over budget must stop); the orchestrator's
PipelineCancelled is a BaseException and passes through ``except Exception`` untouched;
any other failure records ``unchecked:error:<Type>`` instead of breaking the report.
Everything except ``run_spine_backbone_check`` is pure and offline-testable.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils.llm_client import CLI_PROVIDERS
from ..utils.probability_parse import PROB_REVIEW
from ..utils.telemetry import BudgetExceeded
from . import forecast_extractor as _fe
from .ensemble import _norm_name

SCHEMA = "backbone-sensitivity/v1"
NOTE = "shadow diagnostic; probabilities unchanged"

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
    """The admission-time ``backbone_check`` pin, snapshotted from the ambient Config."""
    return {
        "enabled": bool(getattr(config, "BACKBONE_CHECK_ENABLED", False)),
        "providers": parse_providers(getattr(config, "BACKBONE_CHECK_PROVIDERS", "")),
        "max_abs_delta": _as_float(getattr(config, "BACKBONE_CHECK_MAX_ABS_DELTA",
                                           DEFAULT_MAX_ABS_DELTA)),
    }


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
    threshold = _as_float(max_abs_delta)
    if threshold is None or not 0.0 < threshold <= 1.0:
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
             calls: int = 0, max_abs_delta: Any = None,
             skipped: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """The ``forecast.quality.backbone_sensitivity`` record. ``calls`` counts spine draws
    attempted (a draw's JSON repair turn, if any, is not counted separately)."""
    return {
        "schema": SCHEMA,
        "providers": {"primary": primary, "secondary": secondary},
        "status": status,
        "cross": cross,
        "within": within,
        "calls": int(calls),
        "max_abs_delta": max_abs_delta,
        "skipped": list(skipped or []),
        "note": NOTE,
    }


def unchecked_artifact(reason: str) -> Dict[str, Any]:
    """An ``unchecked:<reason>`` record for a check that failed before any comparison."""
    return artifact(f"{UNCHECKED}:{reason}")


# ------------------------------------------------------------------ the check
def _identity(client: Any, model: Any) -> Dict[str, Any]:
    return {"provider": str(getattr(client, "provider", "") or "").lower(),
            "model": None if model is None else str(model)}


def _primary_identity(primary_llm: Any) -> Dict[str, Any]:
    """The primary backbone as the spine draw was served: provider plus the strong-tier model
    (the model a chat_json call without a tier resolves to, tier routing included).

    CLI subscription providers ignore the tier alias (claude-cli passes its own ``model``,
    codex-cli none), so their served model is the client's own ``model``.
    """
    resolve = getattr(primary_llm, "_model_for_tier", None)
    provider = str(getattr(primary_llm, "provider", "") or "").lower()
    if callable(resolve) and provider not in CLI_PROVIDERS:
        model = resolve("strong")
    else:
        model = getattr(primary_llm, "model", None)
    return _identity(primary_llm, model)


def _control_client(primary_llm: Any, model: Optional[str]) -> Any:
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
    """The first provider whose client constructs and differs from the primary backbone."""
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
                             max_abs_delta: Any = DEFAULT_MAX_ABS_DELTA) -> Dict[str, Any]:
    """Run the shadow check and return its artifact (see the module docstring).

    ``follow_prompt`` is the spine prompt with ``primary_spine``'s scenario names pinned
    (forecast_extractor.spine_follow_prompt); ``primary_spine`` is the within-backbone
    baseline (the spine before any critique); ``client_factory`` builds a client for a
    provider name (forecast_extractor._build_ensemble_client). No secondary backbone means no
    LLM call. BudgetExceeded propagates; other errors yield ``unchecked:error:<Type>``.
    """
    skipped: List[Dict[str, str]] = []
    primary: Optional[Dict[str, Any]] = None
    secondary: Optional[Dict[str, Any]] = None
    calls = 0

    def _record(status: str, **extra: Any) -> Dict[str, Any]:
        return artifact(status, primary=primary, secondary=secondary, calls=calls,
                        max_abs_delta=_as_float(max_abs_delta), skipped=skipped, **extra)

    try:
        primary = _primary_identity(primary_llm)
        secondary_llm, secondary = _pick_secondary(
            parse_providers(providers), primary, client_factory, skipped)
        if secondary_llm is None:
            return _record(f"{UNCHECKED}:no_distinct_secondary")
        control = _control_client(primary_llm, primary["model"])
        calls += 1
        control_draw = _fe._spine_draw(control, follow_prompt, SPINE_TEMPERATURE, max_tokens)
        calls += 1
        secondary_draw = _fe._spine_draw(secondary_llm, follow_prompt, SPINE_TEMPERATURE,
                                         max_tokens)
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 — shadow diagnostic: record, never break the report
        return _record(f"{UNCHECKED}:error:{type(exc).__name__}")
    for label, draw in (("control", control_draw), ("secondary", secondary_draw)):
        if not _readable(draw):
            return _record(f"{UNCHECKED}:unreadable_draw:{label}")
    cross = scenario_agreement(control_draw, secondary_draw)
    within = scenario_agreement(primary_spine, control_draw)
    return _record(classify(cross, within, max_abs_delta), cross=cross, within=within)
