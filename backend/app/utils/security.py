"""Centralized security helpers: secret redaction, URL/SSRF validation,
``.env`` value sanitization, and path-safe identifiers.

One place to define what "sensitive" means, so every logging / error-response /
persistence surface masks the same things and a future endpoint cannot silently
leak a key. EXECPLAN2: I-8-3, F-13-1, F-8-0, F-8-5, F-13-2, F-8-1.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

# Field names whose *values* must never be logged or echoed.
# Matches api_key/apikey/*_key/key, token/*_token, secret, password, etc.
# The bounded ``key`` alternative avoids over-matching words like "monkey".
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|apikey|secret|password|passwd|authorization|bearer|"
    r"credential|token|(?:^|[_-])keys?(?:$|[_-]))",
    re.I,
)

# Inline secret-looking tokens to scrub from free-text (provider key prefixes).
_SECRET_TOKEN_RE = re.compile(
    r"\b(sk-[A-Za-z0-9_\-]{8,}|sk-cp-[A-Za-z0-9_\-]{8,}|"
    r"AIza[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{20,})"
)

REDACTED = "***REDACTED***"


def redact_secrets(obj: Any) -> Any:
    """Recursively mask values whose key name looks sensitive.

    Returns a *new* structure; the input is not mutated. Non-container values
    pass through except that obvious inline tokens in strings are scrubbed.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                out[k] = REDACTED
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_secrets(v) for v in obj]
    if isinstance(obj, str):
        return _SECRET_TOKEN_RE.sub(REDACTED, obj)
    return obj


def redact_text(text: str) -> str:
    """Scrub inline secret-looking tokens from a free-text string."""
    if not isinstance(text, str):
        return text
    return _SECRET_TOKEN_RE.sub(REDACTED, text)


# ---------------------------------------------------------------- env values

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_env_value(value: str) -> str:
    """Validate a value destined for ``.env``.

    Reject control chars / newlines (which would inject extra ``KEY=VALUE``
    lines or corrupt the file). Returns the trimmed value; raises ``ValueError``
    on anything unsafe so the caller surfaces a clear error.
    """
    if value is None:
        return ""
    s = str(value)
    if _CONTROL_CHARS_RE.search(s):
        raise ValueError("value contains control characters / newlines and cannot be persisted")
    return s.strip()


def quote_env_value(value: str) -> str:
    """Return a python-dotenv-safe RHS for ``KEY=<rhs>``.

    Values with spaces, ``#``, quotes or ``=`` are double-quoted with internal
    quotes/backslashes escaped; simple values are returned verbatim. Assumes the
    value has already passed :func:`sanitize_env_value` (no newlines).
    """
    s = "" if value is None else str(value)
    if s == "" or re.search(r"[\s#=\"'\\]", s):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


# ---------------------------------------------------------------- URL / SSRF

# Always-blocked address families: link-local (incl. cloud metadata
# 169.254.169.254), multicast, reserved, unspecified.
def _is_always_blocked(ip) -> bool:
    return bool(
        ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_safe_url(url: str, *, block_private: bool = False) -> str:
    """Validate an operator-supplied base URL before the server fetches it.

    - require an ``http``/``https`` scheme and a host;
    - always reject link-local (cloud metadata 169.254.169.254), multicast,
      reserved and unspecified addresses;
    - when ``block_private`` is true, also reject loopback/private ranges.

    Loopback/private are allowed by default because this is a local-first tool
    that legitimately points at local LLM servers (e.g. ``http://localhost:11434``);
    set ``APP_BLOCK_PRIVATE_URLS=true`` when the API is exposed beyond loopback.

    Returns the URL on success; raises ``ValueError`` otherwise.
    """
    if not url or not isinstance(url, str):
        raise ValueError("missing URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")

    # Resolve every address the host maps to and reject if any is unsafe
    # (defends against DNS-rebinding to a metadata/internal address).
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise ValueError(f"cannot resolve host: {host}") from exc

    for info in infos:
        addr = str(info[4][0]).split("%")[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        # Loopback is allowed by default (local-first: local LLM servers); only
        # block it under block_private. Otherwise reject metadata/link-local etc.
        if ip.is_loopback:
            if block_private:
                raise ValueError(f"refusing to connect to loopback address {addr}")
            continue
        if _is_always_blocked(ip):
            raise ValueError(f"refusing to connect to blocked address {addr}")
        if block_private and ip.is_private:
            raise ValueError(f"refusing to connect to private address {addr}")
    return url.strip()


# ---------------------------------------------------------------- path-safe ids

# Report / simulation / project / pipeline / graph / task ids are joined into
# filesystem paths (and, for reports and projects, handed to shutil.rmtree), and
# they arrive from URLs, JSON bodies and LLM tool calls. Generated ids
# (report_<hex>, sim_<hex>, proj_<hex>, pipe_<hex>, mirofish_<hex>, uuid4) all fit
# this allow-list. It admits no '.', '/', '\\' or control character, so '.', '..'
# and separators can never reach a join, and ``\Z`` (unlike ``$``) refuses a
# trailing newline. A leading '_' is refused so reserved siblings in the data
# roots (_sim_index.json, _zep_dead_letter, _forecast_ledger) never parse as ids.
_SAFE_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")
SAFE_ID_MAX_LEN = 128


class UnsafeIdError(ValueError):
    """An identifier is not safe to use as a single path component under a data root."""


def is_safe_id(value: Any, *, max_len: int = SAFE_ID_MAX_LEN) -> bool:
    """True when *value* is a str of 1..max_len chars matching the id allow-list."""
    return (
        isinstance(value, str)
        and len(value) <= max_len
        and _SAFE_ID_RE.fullmatch(value) is not None
    )


def safe_id(value: Any, kind: str, *, max_len: int = SAFE_ID_MAX_LEN) -> str:
    """Return *value* unchanged when it is a safe id; raise :class:`UnsafeIdError` otherwise.

    With the default ``max_len`` this is ``\\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\\Z``.
    The error message names only the *kind* and never echoes the rejected value, so
    a hostile id cannot inject lines into logs or error responses.
    """
    if not is_safe_id(value, max_len=max_len):
        raise UnsafeIdError(f"invalid {kind} id")
    return value


def contained_child(
    root: str | os.PathLike[str],
    child_id: Any,
    kind: str,
    *,
    max_len: int = SAFE_ID_MAX_LEN,
) -> str:
    """Join a validated id under *root*, requiring the result to stay inside *root*.

    The id must pass :func:`safe_id`, and the realpath of ``root/child_id`` must be a
    strict descendant of the realpath of *root* (never *root* itself), which also
    refuses a symlink at ``root/child_id`` that points outside the root or back at
    it. Returns the unresolved ``os.path.join(root, child_id)`` string, so callers
    see byte-identical paths to a plain join. Raises :class:`UnsafeIdError`.
    """
    safe_id(child_id, kind, max_len=max_len)
    root_str = os.fspath(root)
    candidate = os.path.join(root_str, child_id)
    real_root = os.path.realpath(root_str)
    real_child = os.path.realpath(candidate)
    if real_child == real_root or os.path.commonpath([real_root, real_child]) != real_root:
        raise UnsafeIdError(f"invalid {kind} id")
    return candidate
