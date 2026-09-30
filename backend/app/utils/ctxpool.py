"""INFRA-9: submit work to a thread pool together with the submitter's contextvars.

``ThreadPoolExecutor`` workers do not inherit ``contextvars``. A task submitted
from a pipeline thread therefore runs without the telemetry run id and stage
(``app.utils.telemetry``): its LLM usage falls back to the single active run,
or to the process-wide ``'_global'`` bucket as soon as two runs overlap, and it
escapes that run's budget guard and outage breaker.

``submit_with_context`` copies the caller's context at submit time and runs the
task inside that copy. Each task gets its own copy because one ``Context``
cannot be entered by two threads at once (``RuntimeError``), and separate
copies keep a task's ContextVar writes invisible to its siblings and to the
submitter.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")


def submit_with_context(executor: ThreadPoolExecutor, fn: Callable[..., _T], /,
                        *args: Any, **kwargs: Any) -> "Future[_T]":
    """``executor.submit(fn, *args, **kwargs)`` run inside a copy of the caller's context.

    Thread executors only: a ``ProcessPoolExecutor`` would have to pickle the
    bound ``Context.run``, and a ``Context`` cannot be pickled (``TypeError``).
    """
    ctx = contextvars.copy_context()
    return executor.submit(ctx.run, fn, *args, **kwargs)
