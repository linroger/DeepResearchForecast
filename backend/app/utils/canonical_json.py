"""Canonical JSON hashing shared by artifact seals and ledger identity keys.

One profile (sorted keys, compact separators, UTF-8 without ASCII escaping,
NaN rejected) so a fingerprint computed in one module always equals the same
fingerprint computed in another.  Moved verbatim from ``actor_context`` (which
re-imports it, so existing importers keep working) so the forecast ledger can
key its rows without importing the actor-context machinery.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_sha256(value: Any) -> str:
    """Hash strict canonical JSON, rejecting NaN and unserialisable objects."""
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
