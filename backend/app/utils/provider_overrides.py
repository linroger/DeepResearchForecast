"""INFRA-6: the per-provider overrides of an OpenAI-compatible request, from one place.

An OpenAI-compatible request can carry three provider-specific overrides:

- the coding-agent User-Agent that the Kimi-for-coding gateway checks;
- the reasoning ``extra_body`` that switches provider thinking off (the *_DISABLE_THINKING
  knobs, Config.reasoning_extra_body);
- the Kimi K2.7 Code gateway's temperature rule.

The LLMClient transport (primary, fast-tier and fallback clients), the OASIS model factory
and the settings / preflight / doctor.sh connectivity probes all read these rules from
openai_compat_request_overrides() (LLMClient applies its temperature rule, provider_temperature(),
to the extra_body it attached), keyed by the provider that actually serves the request.
Before INFRA-6 each of them kept a hand-synced copy.

Pure apart from reading Config, which is imported inside the function (config.py never
imports this module at load time). Imports no LLM SDK or HTTP client (INFRA-13 import fences).
"""

import copy
from typing import Any, Dict, Optional

# Providers whose gateway checks the coding-agent User-Agent. Kimi-for-coding rejects a
# request without a recognised one (access_terminated_error); MiniMax and the rest do not check.
_USER_AGENT_PROVIDERS = frozenset({"kimi"})

# The Kimi K2.7 Code gateway accepts exactly one temperature per thinking mode (1 with thinking
# on, 0.6 with thinking.type=disabled) and rejects any other value with a 400.
_KIMI_TEMPERATURE_THINKING = 1.0
_KIMI_TEMPERATURE_NO_THINKING = 0.6

# The accepted values of LLM_FALLBACK_REASONING_EFFORT, which a fallback client sends as the
# top-level OpenAI-compatible ``reasoning_effort``. Config.validate rejects any other value at
# startup, and LLMClient still refuses one per call.
FALLBACK_REASONING_EFFORTS = ("minimal", "low", "medium", "high")


def openai_compat_request_overrides(
    provider: Optional[str],
    temperature: Optional[float] = None,
    *,
    force_disable_thinking: bool = False,
) -> Dict[str, Any]:
    """The request overrides ``provider`` needs, as a dict with three keys.

    - ``default_headers``: the Kimi coding-agent User-Agent (Config.LLM_USER_AGENT) for kimi,
      ``{}`` for every other provider.
    - ``extra_body``: a deep copy of Config.reasoning_extra_body(provider), or ``{}`` when the
      provider has no body or its thinking knob is off. With ``force_disable_thinking`` it is
      the provider's disable-thinking body whatever the knob says (the connectivity probes
      always switch thinking off so a 16-token reply is not eaten by reasoning). Always a
      fresh object, so a caller may mutate it.
    - ``temperature``: ``temperature`` after the provider's rule. For kimi it is 0.6 when
      ``extra_body`` disables thinking and 1.0 otherwise; every other provider keeps it.
      ``None`` stays ``None``: the caller sends no temperature, so there is nothing to coerce.

    ``provider`` is matched case-insensitively and never falls back to Config.LLM_PROVIDER. An
    empty or unknown provider gets empty headers, an empty extra_body and the temperature unchanged.
    """
    from ..config import Config

    pid = (provider or "").strip().lower()
    headers = {"User-Agent": Config.LLM_USER_AGENT} if pid in _USER_AGENT_PROVIDERS else {}
    if not pid:
        body = None
    elif force_disable_thinking:
        body = Config._DISABLE_THINKING_EXTRA_BODY.get(pid)
    else:
        body = Config.reasoning_extra_body(pid)
    extra_body = copy.deepcopy(body) if body else {}
    return {
        "default_headers": headers,
        "extra_body": extra_body,
        "temperature": provider_temperature(pid, temperature, extra_body),
    }


def provider_temperature(provider: Optional[str], temperature: Optional[float],
                         extra_body: Optional[Dict[str, Any]]) -> Optional[float]:
    """``temperature`` after ``provider``'s rule, given the ``extra_body`` the request sends.

    openai_compat_request_overrides() applies it to the body it returns. LLMClient applies it
    to the extra_body it has just attached to a request, so the temperature always matches the
    thinking mode of the body actually sent: the thinking knobs are read once per request.
    ``provider`` is matched case-insensitively; ``None`` temperature stays ``None``.
    """
    pid = (provider or "").strip().lower()
    if temperature is None or pid != "kimi":
        return temperature
    thinking = (extra_body or {}).get("thinking")
    thinking_disabled = isinstance(thinking, dict) and thinking.get("type") == "disabled"
    return _KIMI_TEMPERATURE_NO_THINKING if thinking_disabled else _KIMI_TEMPERATURE_THINKING
