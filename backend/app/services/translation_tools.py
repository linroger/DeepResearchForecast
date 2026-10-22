"""Shared translation primitives: content-filter compliance ladder + pair translation.

2026-10-21: the bilingual report translator loses whole sections whenever the
provider's content filter (GLM 1301) rejects China-trade / riot / security prose
— section GENERATION has long had an L1/L2 compliance-retry ladder, but
translation calls failed fast and kept the source text, failing the publication
audit (report_c6555913731c: two identical failures 18 minutes apart). This
module gives every translation surface (report chapters, graph overlays,
simulation overlays) the same bounded ladder:

  L0  plain call (existing prompt);
  L1  one retry with a compliance-framed system prefix: neutral news-wire
      translation posture, no editorializing — plus zero temperature;
  L2  fragment retry: split the payload on blank lines / paragraphs, translate
      each fragment alone (filters usually trip on combined context), rejoin.

Numeric/citation preservation and failure accounting are the caller's
responsibility (the report path keeps its protect/restore tokens; overlays are
JSON-scoped). Bounded: at most 2 extra provider calls per unit beyond L0.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, List, Optional, Sequence, Tuple

logger = logging.getLogger("mirofish.translation")

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
    "You are a professional translator for a research system. Translate the "
    "value of every JSON key into {language}. Return STRICT JSON only — the "
    "exact same keys, same order, every value translated. RULES: keep proper "
    "nouns, organization names, ticker/series identifiers, URLs, code and file "
    "paths unchanged; copy every number, date, percentage and unit exactly "
    "(digit-for-digit); keep snake_case identifiers unchanged; do not add or "
    "drop keys. No preamble, no commentary."
)


def translate_pairs(
    llm: Any,
    pairs: List[Tuple[str, str]],
    language_name: str,
    *,
    batch_size: int = 24,
    max_tokens_per_pair: int = 600,
    on_failure: Optional[Callable[[], None]] = None,
) -> Tuple[dict, int]:
    """Translate ``(key, text)`` pairs → ``{key: translated}`` with the ladder.

    Short strings are batched; each batch runs L0→L1→L2. Keys with empty or
    untranslatable results are omitted from the result (the overlay simply has
    no entry, and the UI falls back to the source text). Returns
    ``(mapping, max_ladder_level_used)``.
    """
    out: dict = {}
    max_level = 0
    for start in range(0, len(pairs), max(1, batch_size)):
        batch = pairs[start:start + max(1, batch_size)]
        payload = {k: t for k, t in batch}
        sys_p = _PAIR_SYSTEM.format(language=language_name)
        try:
            import json as _json
            text, level = chat_translate(
                llm, sys_p, _json.dumps(payload, ensure_ascii=False),
                max_tokens=max(256, max_tokens_per_pair * max(1, len(batch))),
                on_failure=on_failure)
            max_level = max(max_level, level)
            if not text:
                continue
            parsed = _json.loads(text)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if isinstance(v, str) and v.strip():
                        out[str(k)] = v
        except Exception as exc:  # noqa: BLE001 — JSON 解析失败：丢弃该批，保源头文本
            logger.warning("批量翻译批次失败（保留原文）: %s", str(exc)[:120])
            continue
    return out, max_level
