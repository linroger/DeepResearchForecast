"""Small shared contracts. Provider response bodies never belong in job errors."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

SCHEMA = "translation-job/v2"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def scope_digest(identity):
    """Exclude scheduling cursors, never resource, source or visibility context."""
    if identity is None:
        return None
    return digest({"policy": "staged-review/v2", "resource": {
        key: value for key, value in identity.items()
        if key not in {"page", "request_digest", "refresh_generation"}}})


class ScopedImport(dict):
    """In-process capability issued only by a resource's validated legacy reader.

    It cannot arrive as an ordinary JSON request/cache value. New receipts carry
    their own scope digest; legacy imports need this explicit reader attestation.
    """
    def __init__(self, value, identity):
        super().__init__(value)
        self.binding = scope_digest(identity)


def trusted_import(value, identity):
    return ScopedImport(value, identity)


def now():
    return datetime.now(timezone.utc).isoformat()


class TranslationError(RuntimeError):
    def __init__(self, code, message, *, retryable=False):
        self.code, self.safe_message, self.retryable = code, message, retryable
        super().__init__(message)


def safe_error(exc, stage):
    if isinstance(exc, TranslationError):
        return {"code": exc.code, "message": exc.safe_message, "retryable": exc.retryable, "stage": stage}
    if isinstance(exc, json.JSONDecodeError):
        code, message, retryable = "invalid_json", "Model returned incomplete or invalid JSON.", True
    elif isinstance(exc, ValueError) and str(exc) in {
        "duplicate model response key", "model response is not a JSON object",
    }:
        code, message, retryable = "invalid_response", "Model response has duplicate keys or is not an object.", True
    elif getattr(exc, "status_code", None) == 429 or "RateLimit" in type(exc).__name__:
        code, message, retryable = "provider_rate_limit", "Translation provider is rate limited; retry later.", False
    elif "Timeout" in type(exc).__name__ or isinstance(exc, TimeoutError):
        code, message, retryable = "provider_timeout", "Translation provider timed out; saved progress is retained.", False
    elif getattr(exc, "status_code", None) in {401, 403}:
        code, message, retryable = "provider_access", "Translation provider access failed; check the existing provider configuration.", False
    else:
        from ..translation_tools import is_content_filter_error
        if is_content_filter_error(exc):
            return {"code": "provider_refusal", "message": "Translation provider declined this content; saved progress is retained.",
                    "retryable": False, "stage": stage}
        # Deliberately do not persist str(exc): SDK errors can include request headers.
        code, message, retryable = "provider_failure", "Translation provider failed; saved progress is retained.", False
    return {"code": code, "message": message, "retryable": retryable, "stage": stage}
