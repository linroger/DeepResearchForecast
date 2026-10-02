"""Atomic file-write helpers.

A watchdog ``SIGKILL`` mid-write, or a polling reader that opens a file while a
writer is still flushing, can otherwise observe a truncated / half-written
artifact and corrupt the cross-stage contract. Every artifact and state writer
should route through these helpers: write to a sibling temp file, ``fsync``, then
``os.replace`` (atomic rename on the same filesystem).

EXECPLAN2: F-0-4, F-6-13, F-7-6, F-8-1 (atomic-write-everywhere theme).
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from typing import Any


def write_text_atomic(
    path: str, text: str, *, encoding: str = "utf-8", fsync: bool = True
) -> None:
    """Atomically write *text* to *path* (create parent dir if needed).

    The temp-file + ``os.replace`` rename is always atomic, so a reader never
    observes a half-written file regardless of *fsync*. ``fsync`` only controls
    whether the bytes are forced to the platter before the rename:

    - ``fsync=True`` (default) survives a hard power loss / kernel panic — keep
      it for durable artifacts (forecast.json, dossiers, terminal state).
    - ``fsync=False`` skips the (slow) flush for high-frequency status/progress
      writes that are overwritten seconds later anyway; the rename is still
      atomic, so concurrent pollers stay safe. (ATOMIC-1)
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            if fsync:
                os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_secret_text_atomic(path: str, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write a secret-bearing file (e.g. ``.env``) readable only by its owner.

    Same temp-file + ``fsync`` + ``os.replace`` contract as :func:`write_text_atomic`,
    but the owner-only mode is explicit rather than an unasserted side effect of
    ``tempfile.mkstemp``: the temp file is created with ``O_CREAT | O_EXCL`` at
    ``0o600`` and ``fchmod``-ed to ``0o600`` (independent of the umask), so the file
    that replaces *path* is always ``0600``. Failures propagate to the caller, and a
    failed write never leaves the temp file behind.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, f".tmp-{secrets.token_hex(8)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(
    path: str,
    obj: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = 2,
    fsync: bool = True,
    allow_nan: bool = True,
) -> None:
    """Atomically serialize *obj* to JSON at *path*.

    *fsync* is forwarded to :func:`write_text_atomic`; pass ``fsync=False`` at
    high-frequency status/progress sites only. (ATOMIC-1)

    ``allow_nan=False`` refuses NaN / +/-Infinity with a
    :class:`~app.utils.numeric.NonFiniteJSONError` (a ``ValueError``) naming the
    offending JSON paths and *path*; nothing is written. (INFRA-4)
    """
    try:
        text = json.dumps(
            obj,
            ensure_ascii=ensure_ascii,
            indent=indent,
            default=str,
            allow_nan=allow_nan,
        )
    except ValueError as exc:
        if allow_nan:
            raise
        # Lazy: this leaf helper is imported by subprocess scripts; keep its import cheap.
        from .numeric import raise_nonfinite
        raise_nonfinite(obj, exc, artifact=path)
    write_text_atomic(path, text, fsync=fsync)
