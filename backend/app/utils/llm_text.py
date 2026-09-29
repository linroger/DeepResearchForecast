"""Pure text helpers that normalize one LLM completion (INFRA-1).

Stdlib only and free of ``Config``: the backend ``LLMClient`` uses these to turn
a raw OpenAI-compatible reply into plain text plus a finish reason from one
fixed vocabulary.

The semantics are ported from the research gateway
(``deerflow_bridge/research_gateway.py``: ``_flatten_content``,
``_remove_think_blocks``, ``_strip_think`` and the finish-reason frozensets), so
both transports read a completion the same way. The gateway runs in the
deer-flow venv and never imports backend ``app.*`` modules, so it keeps its own
copy; ``tests/test_llm_text.py`` pins the finish-reason vocabulary to it.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------- content

_TEXT_PART_TYPES = frozenset({"text", "output_text"})


def flatten_content(content: Any) -> str:
    """Flatten a message ``content`` to plain text.

    Accepts a string, ``None`` (empty text) or a list/tuple of parts. A part
    contributes text when it is a bare string, a dict whose ``type`` is
    ``text``/``output_text`` (a missing type counts as ``text``) with a string
    ``text``, or an object with the same ``type``/``text`` attributes. Reasoning,
    thinking, image and tool-use parts are skipped. Parts are joined with a
    single space, as the research gateway does. Any other value is ``str()``-ed.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if isinstance(part, dict):
                kind, text = part.get("type", "text"), part.get("text")
            else:
                kind, text = getattr(part, "type", "text"), getattr(part, "text", None)
            if kind in _TEXT_PART_TYPES and isinstance(text, str):
                parts.append(text)
        return " ".join(parts)
    return str(content)


# ---------------------------------------------------------------- think tags

_THINK_TAG_RE = re.compile(r"<(/?)think>", re.IGNORECASE)
_DANGLING_THINK_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)
_THINK_CLOSE = "</think>"


def _remove_think_blocks(text: str) -> str:
    """``text`` without ``<think>...</think>`` blocks, each opener closed by the
    next closer, in one linear pass (a backtracking regex re-scans to the end of
    the text for every unclosed opener)."""
    out: list[str] = []
    pos = 0
    opener: int | None = None
    for tag in _THINK_TAG_RE.finditer(text):
        if not tag.group(1):
            if opener is None:
                opener = tag.start()
        elif opener is not None:
            out.append(text[pos:opener])
            pos = tag.end()
            opener = None
    out.append(text[pos:])
    return "".join(out)


def _scan_think(text: str) -> tuple[str, bool, bool]:
    """Return ``(clean, changed, dangling)`` for ``text``.

    ``clean`` drops closed ``<think>`` blocks, everything up to the last orphan
    ``</think>`` (providers that omit the opening tag) and a dangling unclosed
    ``<think>`` to the end of the text (reasoning cut by the output cap), then
    strips surrounding whitespace. ``changed`` is True when any think markup was
    removed; ``dangling`` is True when an unclosed opener was cut.
    """
    if not text:
        return "", False, False
    cleaned = _remove_think_blocks(text)
    orphan = cleaned.lower().rfind(_THINK_CLOSE)
    if orphan != -1:
        cleaned = cleaned[orphan + len(_THINK_CLOSE):]
    without_dangling = _DANGLING_THINK_RE.sub("", cleaned)
    dangling = without_dangling != cleaned
    return without_dangling.strip(), without_dangling != text, dangling


def strip_think(text: str) -> tuple[str, bool]:
    """Remove inline reasoning from ``text``; return ``(clean, changed)``.

    Removes closed ``<think>...</think>`` blocks, any leading text up to an orphan
    ``</think>`` and a dangling unclosed ``<think>`` to the end of the text, then
    strips whitespace. ``changed`` reports whether think markup was removed
    (whitespace trimming alone does not count). A reply that is only a dangling
    ``<think>`` returns ``('', True)``.
    """
    clean, changed, _ = _scan_think(text)
    return clean, changed


def has_dangling_think(text: str) -> bool:
    """True when ``text`` carries an unclosed ``<think>`` after closed blocks and
    orphan closers are accounted for: the reply was cut mid-reasoning."""
    return _scan_think(text)[2]


# ---------------------------------------------------------------- finish reason

FINISH_REASONS = ("stop", "length", "tool_calls", "content_filter", "error", "unknown")

# Supersets of the research gateway's finish sets (research_gateway.py
# _CONTENT_FILTER_FINISH_REASONS / _TRUNCATION_FINISH_REASONS /
# _ABORTED_FINISH_REASONS), plus the Anthropic, Gemini and OpenAI Responses
# spellings of the same outcomes.
_FINISH_ALIASES: dict[str, frozenset[str]] = {
    "stop": frozenset({"stop", "end_turn", "stop_sequence", "eos", "end", "complete", "completed"}),
    "length": frozenset({"length", "max_tokens", "max_output_tokens", "model_length"}),
    "tool_calls": frozenset({"tool_calls", "tool_call", "function_call", "tool_use"}),
    "content_filter": frozenset({
        "content_filter", "content_filtered", "sensitive", "safety", "recitation",
        "blocklist", "prohibited_content", "spii", "refusal",
    }),
    "error": frozenset({"error", "network_error", "insufficient_system_resource", "abort", "aborted"}),
}
_FINISH_LOOKUP: dict[str, str] = {
    alias: reason for reason, aliases in _FINISH_ALIASES.items() for alias in aliases
}


def normalize_finish_reason(raw: Any) -> str:
    """Map a provider finish reason onto ``FINISH_REASONS``.

    Case-insensitive; enum values are read through ``.value``. ``None``, an empty
    string or an unrecognised value gives ``'unknown'``, never ``'stop'``.
    """
    if raw is None:
        return "unknown"
    value = getattr(raw, "value", raw)
    key = str(value).strip().lower()
    return _FINISH_LOOKUP.get(key, "unknown")
