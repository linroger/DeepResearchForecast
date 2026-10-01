"""INFRA-3: pure recovery policy for model replies cut by the output cap.

Reasoning models (MiniMax / GLM / Kimi) can spend the whole ``max_tokens`` budget on
thinking and answer with empty content and finish_reason ``length``. LLMClient then re-issues
the same request at once with a larger cap (``LLM_LENGTH_ESCALATION``); this module decides
the next cap. Stdlib only, no I/O and no Config import, so the schedule is unit-testable.
"""

from typing import Optional

# The smallest cap an escalated request is sent with: a 64-token probe goes to 1024, not 128.
DEFAULT_FLOOR = 1024
# Tokens kept free between the prompt and the context window when clamping to the window.
DEFAULT_RESERVE = 1024


def next_max_tokens(current: Optional[int], *, floor: int = DEFAULT_FLOOR, ceiling: int,
                    context_window: Optional[int] = None, prompt_tokens: Optional[int] = None,
                    reserve: int = DEFAULT_RESERVE) -> Optional[int]:
    """The ``max_tokens`` to re-issue a length-truncated empty reply with; None = no headroom.

    The cap doubles, but never below ``floor`` (``current`` None starts at ``floor * 4``). It
    is clamped to ``ceiling`` and, when both ``context_window`` and ``prompt_tokens`` are
    known, to ``context_window - prompt_tokens - reserve``. Returns None when the clamped
    value is not strictly greater than ``current`` (or not positive), so a caller at its
    ceiling stops escalating instead of re-sending the same request.
    """
    target = floor * 4 if current is None else max(current * 2, floor)
    target = min(target, ceiling)
    if context_window and prompt_tokens is not None:
        target = min(target, context_window - prompt_tokens - reserve)
    if target <= 0 or (current is not None and target <= current):
        return None
    return target
