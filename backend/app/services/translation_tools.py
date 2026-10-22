"""Shared provider admission and model-led field translation adapters.

The active pair producer sends raw readable entries to model_translation and
persists its reviewed receipts. Token-era validators and chat_translate's
content-filter ladder remain for explicit historical callers and controls; the
active pair/cache path never invokes those spelling-based validators or ladder.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import deque
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, List, Optional, Sequence, Tuple

logger = logging.getLogger("mirofish.translation")


class _TranslationAdmission:
    """One FIFO admission queue shared by all translation clients in this process."""

    def __init__(self):
        self.condition = threading.Condition()
        self.waiters = deque()
        self.active = 0

    @staticmethod
    def limit():
        try:
            requested = int(os.environ.get("DRF_TRANSLATION_MAX_CONCURRENCY", "1"))
        except (TypeError, ValueError):
            requested = 1
        return max(1, min(4, requested))

    @contextmanager
    def slot(self):
        ticket = object()
        with self.condition:
            self.waiters.append(ticket)
            try:
                while self.waiters[0] is not ticket or self.active >= self.limit():
                    self.condition.wait()
                self.waiters.popleft()
                self.active += 1
                self.condition.notify_all()
            except BaseException:
                # An interrupted waiter must not prevent everyone behind it
                # from acquiring a later slot.
                self.waiters.remove(ticket)
                self.condition.notify_all()
                raise
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


# A module reload must not create a second gate while older wrappers are active.
if "_TRANSLATION_ADMISSION" not in globals():
    _TRANSLATION_ADMISSION = _TranslationAdmission()


class _TranslationClient:
    __slots__ = ("_client",)
    _drf_translation_client = "translation-client/v1"

    def __init__(self, client):
        object.__setattr__(self, "_client", client)

    def __getattr__(self, name):
        # Resolve the real attribute first. Missing chat/chat_json stays missing
        # for callers that select protocols with hasattr(). Do not catch errors
        # from a real method/property or turn them into a capability fallback.
        attribute = getattr(self._client, name)
        if name not in {"chat", "chat_json"} or not callable(attribute):
            return attribute

        @wraps(attribute)
        def admitted(*args, **kwargs):
            with _TRANSLATION_ADMISSION.slot():
                return attribute(*args, **kwargs)
        return admitted

    def __setattr__(self, name, value):
        setattr(self._client, name, value)


def translation_client(llm):
    """Idempotent attribute-preserving proxy for translation provider calls only.

    chat/chat_json share a process-wide admission limit, default1, configured by
    DRF_TRANSLATION_MAX_CONCURRENCY (clamped1..4). The slot covers the underlying
    client call, including its retries, and always releases on failure. This is
    not a cross-process/provider-account quota or a generic LLMClient change.
    """
    if getattr(type(llm), "_drf_translation_client", None) == "translation-client/v1":
        return llm
    return _TranslationClient(llm)

_FILTER_RE = re.compile(
    r"1301|content.?filter|敏感内容|sensitive content|new_sensitive", re.I)


def is_content_filter_error(exc: BaseException) -> bool:
    """True for provider content-filter rejections (the non-retryable class
    that a compliance reframe can still rescue)."""
    return bool(_FILTER_RE.search(str(exc or "")))


_COMPLIANCE_PREFIX = (
    "CONTENT-COMPLIANCE TRANSLATION MODE. You are translating published news "
    "and analytic material for an internal research archive. This is a neutral, "
    "faithful, news-wire-style rendering exercise: report what the source says "
    "in the target language without endorsing, amplifying, criticizing or "
    "adding to any claim. Translate plainly and professionally; do not "
    "editorialize. "
)


def chat_translate(
    llm: Any,
    system_prompt: str,
    content: str,
    *,
    max_tokens: int,
    on_failure: Optional[Callable[[], None]] = None,
    fragment_join: str = "\n\n",
    temperature: float = 0.1,
) -> Tuple[str, int]:
    """Translate one unit with the L0→L1→L2 compliance ladder.

    Returns ``(text, ladder_level)``; on total failure returns ``("", 0)`` and
    calls ``on_failure`` once per failed provider call (the caller's failure
    counter for audit honesty). Never raises.
    """
    def _call(sys_p: str, payload: str, temp: float) -> str:
        return llm.chat(
            messages=[{"role": "system", "content": sys_p},
                      {"role": "user", "content": payload}],
            temperature=temp, max_tokens=max_tokens, tier="strong",
        )

    def _fail(exc: BaseException) -> None:
        if on_failure is not None:
            try:
                on_failure()
            except Exception:  # noqa: BLE001
                pass

    # L0 — plain
    try:
        return _call(system_prompt, content, temperature), 0
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
        if not is_content_filter_error(exc):
            return "", 0
        logger.info("翻译内容审查拦截（L0），升级合规重试 L1: %s", str(exc)[:120])

    # L1 — compliance-framed retry
    try:
        return _call(_COMPLIANCE_PREFIX + system_prompt, content, 0.0), 1
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
        if not is_content_filter_error(exc):
            return "", 0
        logger.info("翻译 L1 仍被拦截，升级分片重试 L2")

    # L2 — fragment retry (filters usually trip on combined context)
    fragments = [f for f in re.split(r"\n\s*\n", content) if f.strip()]
    if len(fragments) < 2:
        return "", 0
    out: List[str] = []
    for frag in fragments:
        try:
            out.append(_call(_COMPLIANCE_PREFIX + system_prompt, frag, 0.0))
        except Exception as exc:  # noqa: BLE001
            _fail(exc)
            if is_content_filter_error(exc):
                # 单片仍被过滤：保留该片原文（诚实降级，交上层审计计数）
                out.append(frag)
            else:
                return "", 0
    return fragment_join.join(out), 2


_PAIR_SYSTEM = (
    "Translate every JSON value into {language}. Return strict JSON with exactly "
    "the supplied keys and string values. Translate substantive prose, labels and "
    "headings; conventional English proper names and technical terms may remain. "
    "Copy every ⟦KEEP:...⟧ token exactly once in its original semantic position. "
    "These tokens contain protected numbers, dates, quantities, units, citations, "
    "URLs and machine identifiers; never change, drop or add one. No commentary."
)

# Protect whole quantity/date phrases: preserving digits alone allows a change
# from million to billion. Existing report recognizers remain the authority for
# those phrases; overlays deliberately retain their exact original spelling.
from .translation_dates import DATE_PATTERN
from .translation_quantities import QUANTITY_PATTERN
from collections import Counter
import json

# Shared with long-form/localized-forecast factual admission. SI prefixes are
# case-sensitive: mW and MW differ by nine orders of magnitude. Long forms
# precede their prefixes; boundaries allow numeric attachment but not words/IDs.
FACT_UNIT_PATTERN = (
    r"(?<![A-Za-z_µμ])(?-i:(?:TWh|GWh|MWh|kWh|mWh|uWh|µWh|μWh|Wh|"
    r"TW|GW|MW|kW|mW|uW|µW|μW|W))(?![A-Za-z0-9_µμ])"
)

_PROTECTED = re.compile(
    r"`[^`\n]+`|https?://[^\s<>()]+|\[[Ss]\d+(?:-[A-Za-z])?\]"
    r"|" + DATE_PATTERN + r"|" + QUANTITY_PATTERN
    + r"|[-+−]?(?:\d+(?:\.\d+)?|\.\d+)[eE][-+−]?\d+"
    r"|(?<![A-Za-z0-9_])(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])[A-Za-z]+_[A-Za-z0-9_]+"
    r"|[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+|\.\d+)(?:\.\d+)?(?:[eE][-+−]?\d+)?"
    r"(?:[ \u00a0]*[–—-][ \u00a0]*[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+|\.\d+)(?:\.\d+)?)?"
    r"(?:\s*(?:" + FACT_UNIT_PATTERN
    + r"|%|percent(?:age points)?|basis points|bps|USD|EUR|CNY|RMB|dollars|"
    r"kg|tonnes|barrels|mb/d|bpd|million|billion|trillion))?"
    r"|[$€£¥]|°[CF]|" + FACT_UNIT_PATTERN
    + r"|\b(?:USD_per_contract|USD|EUR|CNY|RMB|mb/d|bpd|km/h|mph)\b",
    re.I,
)
_KEEP = re.compile(r"⟦KEEP:[A-Z]+⟧")
_CJK = re.compile(r"[\u3400-\u9fff]")


def _suffix(index: int) -> str:
    out = ""
    while True:
        index, digit = divmod(index, 26)
        out = chr(65 + digit) + out
        if not index:
            return out
        index -= 1


def _protect_pair(text: str):
    tokens = {}
    def hide(match):
        token = "⟦KEEP:" + _suffix(len(tokens)) + "⟧"
        # Source-authored placeholders must never be interpreted as ours.
        while token in text or token in tokens:
            token = token[:-1] + "X⟧"
        tokens[token] = match.group(0)
        return token
    return _PROTECTED.sub(hide, text), tokens


def _technical(text: str) -> bool:
    value = text.strip()
    words = re.findall(r"[A-Za-z]+", value)
    return (not words or bool(re.fullmatch(r"[A-Z0-9_./:+-]+", value))
            or bool(re.fullmatch(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+", value))
            or (len(words) <= 4 and all(w[0].isupper() for w in words)
                and not re.search(r"[.!?]", value)))


def _substantive_mandarin(text: str) -> bool:
    # A boilerplate label is not target-language coverage of an English body.
    body = re.sub(r"^\s*(?:中文译文|中文翻译|翻译结果|译文|翻译|中文)\s*[:：]\s*", "", text)
    if not _CJK.search(body) and not _technical(body):
        return False
    # Inspect separate ordinary clauses, including shorter sentences separated
    # by periods. Names/acronyms and conventional short technical phrases remain
    # allowed; a Mandarin prefix cannot hide multiple copied English sentences.
    ordinary_words = 0
    for match in re.finditer(r"[A-Za-z]+(?:[’'-][A-Za-z]+)*(?:[ \t,]+[A-Za-z]+(?:[’'-][A-Za-z]+)*)*", body):
        clause = match.group(0)
        words = re.findall(r"[A-Za-z]+", clause)
        if _technical(clause):
            continue
        ordinary_words += len(words)
        following = body[match.end():].lstrip(" \t")
        if len(words) >= 5 or (len(words) >= 3 and following.startswith((".", "!", "?"))):
            return False
    return ordinary_words <= max(4, len(_CJK.findall(body)))


def valid_pair_translation(source: str, target: str, language_name: str) -> bool:
    """Legacy token-era validator; model-led cache reads use valid_receipt instead."""
    if not isinstance(target, str) or not target.strip() or len(target) > max(200, len(source) * 5):
        return False
    if Counter(m.group(0) for m in _PROTECTED.finditer(source)) != Counter(
            m.group(0) for m in _PROTECTED.finditer(target)):
        return False
    rest = _PROTECTED.sub(" ", target)
    if "Chinese" in language_name or "中文" in language_name:
        if not _substantive_mandarin(rest):
            return False
    elif "English" in language_name and len(_CJK.findall(rest)) > 3:
        return False
    return True


def _restore_pair_tokens(protected: str, candidate: str, tokens: dict) -> str:
    """Restore only separators proven between these exact source placeholders.

    Q1 and 2027 may become adjacent KEEP tokens in a model response. A source
    whitespace boundary prevents their restoration as the different ID Q12027.
    Real source identifiers are one protected token and are never split here.
    """
    spans = list(_KEEP.finditer(protected))
    for left, right in zip(spans, spans[1:]):
        separator = protected[left.end():right.start()]
        if separator and separator.isspace():
            candidate = candidate.replace(left.group(0) + right.group(0),
                                          left.group(0) + separator + right.group(0))
    return _KEEP.sub(lambda match: tokens.get(match.group(0), match.group(0)), candidate)


def _pair_target_language(language_name: str) -> str:
    value = str(language_name or "").strip().lower()
    if value == "zh" or "chinese" in value or "中文" in value:
        return "zh"
    if value == "en" or "english" in value:
        return "en"
    raise ValueError("unsupported translation language")


def translate_pairs(
    llm: Any, pairs: List[Tuple[str, str]], language_name: str, *,
    batch_size: int = 18, max_tokens_per_pair: int = 600,
    on_failure: Optional[Callable[[], None]] = None, max_calls: int = 48,
    on_progress: Optional[Callable[[dict], None]] = None, context: str = "",
) -> Tuple[dict, int]:
    """Adapt readable field entries to the shared model-led translator.

    The return mapping is VerifiedTranslations, including its receipts, issues
    and explicit client-call count. All translation/review/one-repair calls use
    the same budget and shared provider admission. No numeric/date placeholders,
    restoration or legacy token-multiset validator runs in this active path.

    batch_size/max_tokens_per_pair and the tuple's zero ladder level remain for
    caller compatibility; the core owns coherent bounded grouping/token limits.
    """
    from .model_translation import translate_entries

    provider = translation_client(llm)
    if on_failure is not None:
        class FailureAccountingClient:
            # The delegated provider already owns admission. An idempotent wrap
            # by another translation surface must not acquire a second slot.
            _drf_translation_client = "translation-client/v1"

            def __getattr__(self, name):
                attribute = getattr(provider, name)
                if name not in {"chat", "chat_json"} or not callable(attribute):
                    return attribute

                @wraps(attribute)
                def invoke(*args, **kwargs):
                    try:
                        return attribute(*args, **kwargs)
                    except Exception:
                        try:
                            on_failure()
                        except Exception:
                            pass  # Observability cannot hide the provider error.
                        raise
                return invoke
        client = FailureAccountingClient()
    else:
        client = provider
    translated = translate_entries(client, pairs, _pair_target_language(language_name),
        context=context, max_calls=max_calls, on_progress=on_progress)
    return translated, 0
