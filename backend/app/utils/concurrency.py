"""Context-propagating concurrency helpers.

2026-10-21 (ISSUES LOG-16): ``ThreadPoolExecutor`` workers do NOT inherit the
submitting thread's ``contextvars`` — every LLM call made inside such a worker
loses its ``_current_run``/``_current_stage`` and falls into the ``'_global'``
meter bucket (warnings at 20/100/500 calls across all six audited runs; per-run
budget/cost attribution silently distorted).  ``ContextThreadPoolExecutor``
copies the submitting context at ``submit()`` time so workers run inside it.

Drop-in replacement: ``ContextThreadPoolExecutor(max_workers=...)`` instead of
``ThreadPoolExecutor(max_workers=...)``.  A few hot sites already inline the
``parent_context.copy().run`` pattern (report section pool RPT-9, forecast
localization) — those are fine; this class exists so new sites get it for free.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


class ContextThreadPoolExecutor(ThreadPoolExecutor):
    """``ThreadPoolExecutor`` whose tasks run in a copy of the submitter's context.

    The context is captured on the SUBMITTING thread (so each task inherits the
    context that was current when its work was queued, not when the pool was
    created) — matching the semantics asyncio tasks and ``asyncio.to_thread``
    already provide.
    """

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any):
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)
