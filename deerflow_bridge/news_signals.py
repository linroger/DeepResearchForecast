"""Bounded contextual sources and immutable run-local capture storage.

No provider or filesystem work occurs at import. Runtime credentials are used
only as HTTP headers. This module also supports deployment as a bare module.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

CONTEXT_FILENAME = "news_market_context.json"
MAX_CONTEXT_BYTES = 2_000_000
MAX_RESPONSE_BYTES = 512_000
MAX_ITEMS = 120
MAX_QUERIES = 32
_STATES = frozenset({"ok", "verified_empty", "disabled", "unavailable", "forbidden",
                     "rate_limited", "timeout", "budget_exhausted", "partial", "unsupported"})
_PROVIDERS = frozenset({"newsapi", "reddit", "polymarket", "kalshi", "metaculus"})
_KINDS = frozenset({"news_snippet", "social_post", "market_quote", "community_forecast"})
_ENDPOINTS = {("newsapi.org", "/v2/everything"), ("www.reddit.com", "/search.json")}
_ELIGIBILITY = {"context_only": True, "anchor": False, "resolution": False}
_CLIENTS = {}
_LOCKS = {}
_CACHE_LOCK = threading.RLock()


class ContextIntegrityError(ValueError):
    """A present capture cannot safely be used as research evidence."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical({k: v for k, v in value.items() if k != "sha256"})).hexdigest()


def _text(value, limit=500):
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:limit]


def _query(value):
    return _text(value, 500)


def _question_hash(question):
    # Only the trusted launcher supplies this internal cross-lane binding.
    parent = os.environ.get("NEWS_CONTEXT_QUESTION_SHA256")
    if parent is not None:
        if not re.fullmatch(r"[a-f0-9]{64}", parent):
            raise ContextIntegrityError("invalid_parent_question_identity")
        return parent
    # Direct-run identity is independent of the shorter provider query limit.
    return hashlib.sha256(" ".join(str(question or "").split()).encode("utf-8")).hexdigest()


def _utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _date(value, *, end_of_day=False):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            raw = str(value)
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if len(raw) == 10 and end_of_day:
                parsed += timedelta(days=1, microseconds=-1)
        except (ValueError, TypeError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _language(value):
    name = _text(value, 40).lower().replace("_", "-")
    aliases = {"english": "en", "chinese": "zh", "mandarin": "zh", "中文": "zh",
               "简体中文": "zh", "繁體中文": "zh", "simplified chinese": "zh", "traditional chinese": "zh",
               "german": "de", "french": "fr", "spanish": "es", "portuguese": "pt",
               "russian": "ru", "arabic": "ar", "italian": "it", "dutch": "nl",
               "hebrew": "he", "norwegian": "no", "swedish": "sv", "urdu": "ud"}
    return aliases.get(name, "zh" if name.startswith("zh-") else name or "en")[:16]


def _identity_date(value):
    if value is None or value == "":
        return None
    parsed = _date(value)
    if parsed is None:
        raise ContextIntegrityError("invalid_cutoff")
    if isinstance(value, str) and len(value) == 10:
        return value
    return parsed.isoformat().replace("+00:00", "Z")


def _url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return ""
        if parts.port not in {None, 80, 443}:
            return ""
        params = []
        for key, val in parse_qsl(parts.query, keep_blank_values=True):
            low = key.lower()
            if low in {"apikey", "api_key", "key", "token", "access_token", "authorization"}:
                return ""
            if low.startswith("utm_") or low in {"fbclid", "gclid"}:
                continue
            params.append((key, val))
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/",
                           urlencode(sorted(params)), ""))
    except ValueError:
        return ""


def _env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() not in {"0", "false", "no", "off", ""}


def _env_num(name, default, maximum):
    try:
        number = float(os.environ.get(name, str(default)))
        if not math.isfinite(number):
            return default
        return min(maximum, max(0, number))
    except (ValueError, TypeError):
        return default


def _root_path(artifact_dir):
    if artifact_dir is None or str(artifact_dir).strip() == "":
        return None
    raw = os.fspath(artifact_dir)
    if ".." in Path(raw).parts:
        raise ContextIntegrityError("unsafe_artifact_root")
    return Path(os.path.abspath(raw))


@contextmanager
def _directory(root, *, create=False):
    """Pin a verified existing ancestor, then use no-follow relative operations.

    The descriptor must match the inode inspected before opening it. This also
    avoids opening unrelated filesystem roots in a restricted offline process.
    """
    anchor, expected = None, None
    missing = []
    for index in range(1, len(root.parts)):
        candidate = Path(*root.parts[:index + 1])
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            missing = list(root.parts[index:])
            break
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ContextIntegrityError("unsafe_artifact_root")
        anchor, expected = candidate, info
    if anchor is None or (missing and not create):
        raise FileNotFoundError
    descriptor = None
    try:
        try:
            descriptor = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            actual = os.fstat(descriptor)
            if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                raise ContextIntegrityError("artifact_root_changed")
            for part in missing:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
        except OSError:
            raise ContextIntegrityError("unsafe_artifact_root") from None
        # Exceptions from the caller, especially TimeoutError, retain their type.
        yield descriptor
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate(value, *, require_sealed=True, verify_digest=True):
    try:
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
            raise ValueError
        required = {"generation_id", "question_sha256", "language", "as_of", "created_at",
                    "sealed", "providers", "queries", "items", "sha256"}
        if not required.issubset(value) or not isinstance(value["sealed"], bool):
            raise ValueError
        if require_sealed and not value["sealed"]:
            raise ContextIntegrityError("unsealed_context")
        if not re.fullmatch(r"[a-f0-9]{64}", value["question_sha256"]):
            raise ValueError
        if not isinstance(value["generation_id"], str) or not 1 <= len(value["generation_id"]) <= 128:
            raise ValueError
        if not isinstance(value["language"], str) or len(value["language"]) > 16:
            raise ValueError
        if value["as_of"] is not None and _identity_date(value["as_of"]) != value["as_of"]:
            raise ValueError
        if not _date(value["created_at"]):
            raise ValueError
        if "acquisition_seconds" in value and (
                type(value["acquisition_seconds"]) not in {int, float}
                or not math.isfinite(value["acquisition_seconds"])
                or value["acquisition_seconds"] < 0):
            raise ValueError
        if not isinstance(value["providers"], dict) or not set(value["providers"]).issubset(_PROVIDERS):
            raise ValueError
        if not isinstance(value["queries"], list) or len(value["queries"]) > MAX_QUERIES:
            raise ValueError
        if not isinstance(value["items"], list) or len(value["items"]) > MAX_ITEMS:
            raise ValueError
        for result in value["queries"]:
            if (not isinstance(result, dict) or result.get("provider") not in _PROVIDERS
                    or not isinstance(result.get("query"), str) or len(result["query"]) > 500
                    or not isinstance(result.get("status"), dict)
                    or result["status"].get("state") not in _STATES
                    or not isinstance(result["status"].get("attempted"), bool)
                    or not isinstance(result.get("items"), list)
                    or not re.fullmatch(r"[a-f0-9]{64}", result.get("request_id", ""))):
                raise ValueError
        for item in value["items"] + [row for result in value["queries"] for row in result["items"]]:
            if (not isinstance(item, dict) or item.get("provider") not in _PROVIDERS
                    or item.get("kind") not in _KINDS
                    or not isinstance(item.get("id"), str)
                    or not item["id"].startswith(item["provider"] + ":")
                    or not item.get("url") or _url(item["url"]) != item["url"]
                    or not isinstance(item.get("eligibility"), dict)
                    or any(item["eligibility"].get(k) is not v for k, v in _ELIGIBILITY.items())):
                raise ValueError
        if not isinstance(value["sha256"], str) or (verify_digest and value["sha256"] != _digest(value)):
            raise ContextIntegrityError("context_digest_mismatch")
        if len(_canonical(value)) > MAX_CONTEXT_BYTES:
            raise ValueError
    except ContextIntegrityError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ContextIntegrityError("invalid_context_schema") from None
    return value


def _read(descriptor, *, require_sealed):
    try:
        fd = os.open(CONTEXT_FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=descriptor)
    except FileNotFoundError:
        return {}
    except OSError:
        raise ContextIntegrityError("unsafe_context_file") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_CONTEXT_BYTES:
            raise ContextIntegrityError("unsafe_context_file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_CONTEXT_BYTES + 1)
        if len(raw) > MAX_CONTEXT_BYTES:
            raise ContextIntegrityError("oversized_context")
        try:
            value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError, RecursionError):
            raise ContextIntegrityError("invalid_context_json") from None
        return _validate(value, require_sealed=require_sealed)
    finally:
        os.close(fd)


def _write(descriptor, value):
    value["sha256"] = _digest(value)
    _validate(value, require_sealed=False)
    # Reject a replaced destination even though rename itself would not follow it.
    try:
        info = os.stat(CONTEXT_FILENAME, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ContextIntegrityError("unsafe_context_file")
    except FileNotFoundError:
        pass
    name = ".news-context-" + uuid.uuid4().hex + ".tmp"
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                 dir_fd=descriptor)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(fd)
        os.replace(name, CONTEXT_FILENAME, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        os.close(fd)
        try:
            os.unlink(name, dir_fd=descriptor)
        except FileNotFoundError:
            pass


def _thread_lock(root):
    with _CACHE_LOCK:
        return _LOCKS.setdefault(str(root), threading.RLock())


@contextmanager
def _locked(root, *, deadline=None):
    end = time.monotonic() + _env_num("NEWS_CONTEXT_DEADLINE_SECONDS", 10, 10)
    if deadline is not None:
        supplied = time.monotonic() + float(deadline.remaining()) if hasattr(deadline, "remaining") else float(deadline)
        end = min(end, supplied) if math.isfinite(supplied) else time.monotonic()
    lock = _thread_lock(root)
    if not lock.acquire(timeout=max(0, end - time.monotonic())):
        raise TimeoutError("context_lock_timeout")
    try:
        with _directory(root, create=True) as descriptor:
            while True:
                try:
                    fd = os.open(".news-context.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 0o600, dir_fd=descriptor)
                    break
                except (BlockingIOError, FileNotFoundError):
                    # Concurrent initialization/locking can transiently reject
                    # openat. Retry only while the pinned directory still exists
                    # at the same trusted location; never relax no-follow flags.
                    current = os.fstat(descriptor)
                    try:
                        named = root.lstat()
                    except FileNotFoundError:
                        raise ContextIntegrityError("artifact_root_changed") from None
                    if (not current.st_nlink or (current.st_dev, current.st_ino) != (named.st_dev, named.st_ino)):
                        raise ContextIntegrityError("artifact_root_changed")
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("context_lock_timeout")
                    time.sleep(min(0.02, remaining))
                except OSError as exc:
                    raise ContextIntegrityError("unsafe_context_lock_errno_" + str(exc.errno)) from None
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ContextIntegrityError("unsafe_context_lock")
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        remaining = end - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("context_lock_timeout")
                        time.sleep(min(0.02, remaining))
                yield descriptor
            finally:
                os.close(fd)
    finally:
        lock.release()


def load_context(artifact_dir, *, require_sealed=True):
    """Load validated evidence without contacting a provider or creating files."""
    root = _root_path(artifact_dir)
    if root is None:
        return {}
    try:
        with _directory(root) as descriptor:
            return _read(descriptor, require_sealed=require_sealed)
    except FileNotFoundError:
        return {}


def archive_context(artifact_dir, archive_dir, *, expected_generation_id, expected_sha256):
    """Retire exact proof for a trusted engine's validated new-run transition.

    The engine establishes changed run identity and validates its old state and
    binding before calling. This operation is never an agent tool or a recovery
    mechanism for corrupt/resumed proof. The archive directory must already exist
    beneath the same trusted output root; existing files are never replaced.
    """
    root, archive = _root_path(artifact_dir), _root_path(archive_dir)
    if (root is None or archive is None or archive == root or not archive.is_relative_to(root)
            or not isinstance(expected_generation_id, str) or not 1 <= len(expected_generation_id) <= 128
            or not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)):
        raise ContextIntegrityError("invalid_context_archive_request")
    with _locked(root) as descriptor:
        value = _read(descriptor, require_sealed=False)
        if not value:
            raise ContextIntegrityError("archive_context_missing")
        if value["generation_id"] != expected_generation_id or value["sha256"] != expected_sha256:
            raise ContextIntegrityError("archive_context_binding_mismatch")
        with _CACHE_LOCK:
            cached = _CLIENTS.get(str(root))
            if cached is not None:
                cached._check_identity(value)
                cached._observe(value)
        try:
            with _directory(archive) as archive_fd:
                try:
                    os.stat(CONTEXT_FILENAME, dir_fd=archive_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ContextIntegrityError("context_archive_exists")
                source = os.stat(CONTEXT_FILENAME, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISREG(source.st_mode) or source.st_nlink != 1:
                    raise ContextIntegrityError("unsafe_context_file")
                linked, moved = False, False
                try:
                    # link+unlink is a no-clobber move on supported local filesystems.
                    # Both paths stay descriptor-relative and no symlink is followed.
                    os.link(CONTEXT_FILENAME, CONTEXT_FILENAME, src_dir_fd=descriptor,
                            dst_dir_fd=archive_fd, follow_symlinks=False)
                    linked = True
                    destination = os.stat(CONTEXT_FILENAME, dir_fd=archive_fd, follow_symlinks=False)
                    current = os.stat(CONTEXT_FILENAME, dir_fd=descriptor, follow_symlinks=False)
                    identity = (source.st_dev, source.st_ino)
                    if (not stat.S_ISREG(destination.st_mode)
                            or (destination.st_dev, destination.st_ino) != identity
                            or (current.st_dev, current.st_ino) != identity
                            or destination.st_nlink != 2 or current.st_nlink != 2
                            or current.st_size != source.st_size or current.st_mtime_ns != source.st_mtime_ns):
                        raise ContextIntegrityError("archive_context_changed")
                    # Make the preserved directory entry durable before retiring
                    # the active one. A crash can never turn this into a refetch.
                    os.fsync(archive_fd)
                    os.unlink(CONTEXT_FILENAME, dir_fd=descriptor)
                    moved = True
                    os.fsync(descriptor)
                    os.fsync(archive_fd)
                except FileExistsError:
                    raise ContextIntegrityError("context_archive_exists") from None
                finally:
                    if linked and not moved:
                        try:
                            created = os.stat(CONTEXT_FILENAME, dir_fd=archive_fd, follow_symlinks=False)
                            if (created.st_dev, created.st_ino) == (source.st_dev, source.st_ino):
                                os.unlink(CONTEXT_FILENAME, dir_fd=archive_fd)
                                os.fsync(archive_fd)
                        except FileNotFoundError:
                            pass
        except FileNotFoundError:
            raise ContextIntegrityError("context_archive_directory_missing") from None
        except OSError:
            raise ContextIntegrityError("context_archive_io_failed") from None
        with _CACHE_LOCK:
            registered = _CLIENTS.pop(str(root), None)
            if registered is not None:
                # Do not mutate any old identity/generation/digest. References
                # already handed to callers remain retired and fail closed.
                registered._retired = True
        return value


def _http_get(url, *, headers, timeout, max_bytes):
    parts = urlsplit(url)
    if (parts.scheme != "https" or (parts.hostname, parts.path) not in _ENDPOINTS
            or parts.username or parts.password or parts.port not in {None, 443}):
        raise ValueError("provider_endpoint_not_allowed")
    end = time.monotonic() + timeout
    connection = http.client.HTTPSConnection(parts.hostname, timeout=timeout)
    try:
        connection.request("GET", urlunsplit(("", "", parts.path, parts.query, "")), headers=headers)
        if connection.sock:
            connection.sock.settimeout(max(0.001, end - time.monotonic()))
        response = connection.getresponse()
        raw = bytearray()
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            read_socket = connection.sock or getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
            if read_socket:
                read_socket.settimeout(remaining)
            chunk = response.read1(min(65536, max_bytes + 1 - len(raw)))
            raw.extend(chunk)
            if len(raw) > max_bytes:
                raise ValueError("response_too_large")
            if not chunk:
                return response.status, bytes(raw)
    finally:
        connection.close()


def _budget(kind):
    try:
        if __package__:
            from . import research_budget
        else:
            import research_budget
        admission = (research_budget.admit_attempt("search") if kind == "attempt"
                     else research_budget.admit_network("search"))
        return admission.allowed, _text(admission.reason, 80)
    except ImportError:
        return False, "budget_module_unavailable"


class ContextClient:
    """One trusted artifact root and identity; transports are injectable for tests."""

    def __init__(self, artifact_dir=None, *, question=None, language=None, as_of=None,
                 transport=None, api_key=None, news_enabled=None, social_enabled=None,
                 max_news_requests=None):
        self.artifact_dir = _root_path(artifact_dir)
        existing = load_context(self.artifact_dir, require_sealed=False)
        self.question_sha256 = (_question_hash(question)
                                if question is not None or "NEWS_CONTEXT_QUESTION_SHA256" in os.environ else existing.get("question_sha256", hashlib.sha256(b"").hexdigest()))
        self.language = _language(language) if language is not None else existing.get("language", "en")
        self.as_of = _identity_date(as_of) if as_of is not None else existing.get("as_of")
        self._transport = transport or _http_get
        self._api_key = api_key  # Never serialized; ambient key read only at acquisition.
        self._news_enabled = news_enabled
        self._social_enabled = social_enabled
        self._max_news_requests = max_news_requests
        self._retired = False
        self._bound_generation = existing.get("generation_id")
        self._sealed_digest = existing.get("sha256") if existing.get("sealed") else None
        self._initial = existing or self._new()
        self._initial["sha256"] = _digest(self._initial)
        self._check_identity(self._initial)

    def _new(self):
        return {"schema_version": 1, "generation_id": uuid.uuid4().hex,
                "question_sha256": self.question_sha256, "language": self.language,
                "as_of": self.as_of, "created_at": _utcnow(), "sealed": False,
                "acquisition_seconds": 0,
                "providers": {}, "queries": [], "items": [], "sha256": ""}

    def _check_identity(self, value):
        if self._retired:
            raise ContextIntegrityError("context_generation_retired")
        if any(value.get(key) != getattr(self, key) for key in ("question_sha256", "language", "as_of")):
            raise ContextIntegrityError("context_identity_mismatch")

    def _current(self, descriptor):
        value = _read(descriptor, require_sealed=False)
        if value:
            self._observe(value)
            self._bound_generation = value["generation_id"]
        if not value and self._bound_generation:
            raise ContextIntegrityError("bound_context_missing")
        value = value or json.loads(_canonical(self._initial))
        self._check_identity(value)
        self._observe(value)
        return value

    def _observe(self, value):
        if self._sealed_digest and (not value.get("sealed") or value.get("sha256") != self._sealed_digest):
            raise ContextIntegrityError("sealed_context_changed")
        if self._bound_generation and value["generation_id"] != self._bound_generation:
            raise ContextIntegrityError("bound_generation_changed")
        if value.get("sealed"):
            self._sealed_digest = value["sha256"]
        return value

    def _request_id(self, provider, query):
        return hashlib.sha256(_canonical({"provider": provider, "query": _query(query).casefold(),
                                          "language": self.language, "as_of": self.as_of,
                                          "lookback_days": int(_env_num("NEWSAPI_LOOKBACK_DAYS", 30, 30)),
                                          "method": "context-v1"})).hexdigest()

    def _result(self, provider, query, state, attempted=False, reason=None, **extra):
        status = {"state": state, "attempted": bool(attempted)}
        if reason:
            status["reason"] = reason
        return {"provider": provider, "query": _query(query), "status": status,
                "items": [], "retrieved_at": _utcnow(), **extra}

    def snapshot(self):
        if self._retired:
            raise ContextIntegrityError("context_generation_retired")
        if self.artifact_dir is None:
            return {}
        current = load_context(self.artifact_dir, require_sealed=False)
        if current:
            self._check_identity(current)
            self._observe(current)
            self._bound_generation = current["generation_id"]
            return current
        if self._bound_generation:
            raise ContextIntegrityError("bound_context_missing")
        return json.loads(_canonical(self._initial))

    def _store(self, descriptor, value, provider, query, result):
        request_id = self._request_id(provider, query)
        for previous in value["queries"]:
            if previous["request_id"] == request_id:
                return json.loads(_canonical(previous))
        if value["sealed"]:
            return self._result(provider, query, "unavailable", reason="generation_sealed")
        if len(value["queries"]) >= MAX_QUERIES:
            return self._result(provider, query, "budget_exhausted", reason="query_limit")
        normalized = self._normalize_result(provider, query, result)
        normalized["request_id"] = request_id
        normalized["capture_id"] = value["generation_id"] + ":" + request_id
        available = MAX_ITEMS - len(value["items"])
        if len(normalized["items"]) > available:
            normalized["items"] = normalized["items"][:available]
            normalized["status"]["state"] = "partial"
            normalized["status"]["reason"] = "item_limit"
        for item in normalized["items"]:
            item["capture_id"] = normalized["capture_id"]
            item["normalized_sha256"] = hashlib.sha256(_canonical({k: v for k, v in item.items() if k not in {"source_ref", "normalized_sha256"}})).hexdigest()
        value["queries"].append(normalized)
        value["providers"][provider] = normalized["status"].copy()
        value["items"].extend(normalized["items"])
        _write(descriptor, value)
        self._bound_generation = value["generation_id"]
        return json.loads(_canonical(normalized))

    def _normalize_result(self, provider, query, result):
        if provider not in _PROVIDERS or not isinstance(result, dict) or result.get("provider", provider) != provider:
            raise ValueError("invalid_provider_result")
        status = result.get("status", {})
        state = status.get("state") if isinstance(status, dict) else None
        if state not in _STATES:
            raise ValueError("invalid_provider_status")
        normalized = self._result(provider, query, state, status.get("attempted", False))
        reason = status.get("reason")
        if isinstance(reason, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", reason):
            normalized["status"]["reason"] = reason
        for key, val in status.items():
            if key not in {"state", "attempted", "reason"} and isinstance(val, (int, bool)):
                normalized["status"][_text(key, 60)] = val
        normalized["retrieved_at"] = (_date(result.get("retrieved_at")) or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
        # Explicit metadata fields keep arbitrary transport errors/bodies out of captures.
        for key in ("method", "coverage", "from", "to", "limitations", "price_basis", "comparison_policy", "search_method", "recall_reason"):
            if isinstance(result.get(key), str):
                normalized[key] = _text(result[key], 500)
        for key in ("http_status", "returned", "discarded", "network_requests", "incomplete_recall", "request_count", "recall_complete", "pages", "candidate_count"):
            if isinstance(result.get(key), (int, bool)):
                normalized[key] = result[key]
        if state not in {"ok", "partial"}:
            return normalized
        seen = set()
        for raw in result.get("items", [])[:MAX_ITEMS] if isinstance(result.get("items"), list) else []:
            if not isinstance(raw, dict):
                continue
            url = _url(raw.get("url"))
            kind = raw.get("kind")
            if not url or kind not in _KINDS:
                continue
            native = _text(raw.get("id") or raw.get("native_id"), 220) or hashlib.sha256(url.encode()).hexdigest()
            item_id = native if native.startswith(provider + ":") else provider + ":" + native
            if (item_id, url) in seen:
                continue
            seen.add((item_id, url))
            published = _date(raw.get("published_at"))
            item = {"id": item_id, "provider": provider, "kind": kind,
                    "title": _text(raw.get("title"), 500), "url": url,
                    "published_at": published.isoformat().replace("+00:00", "Z") if published else None,
                    "retrieved_at": normalized["retrieved_at"], "language": _text(raw.get("language"), 16) or self.language,
                    "query": _query(query), "snippet": _text(raw.get("snippet"), 1600),
                    "eligibility": _ELIGIBILITY.copy()}
            for key in ("native_id", "publisher", "publisher_id", "subreddit", "rules", "end_date", "quote_time", "quote_at",
                        "price_basis", "volume_units", "quote_basis", "units", "outcome", "outcome_label", "method", "evidence_sha256",
                        "content_sha256", "contract_type", "event_id", "market_id", "ticker", "forecast_type", "match_status", "comparison_group",
                        "price_unit", "probability_basis", "rules_primary", "rules_secondary", "yes_label", "no_label", "quote_units",
                        "market_type", "metadata_updated_at", "volume_unit", "expiration_time", "strike_type", "status"):
                if key in raw and raw[key] is None:
                    item[key] = None
                elif isinstance(raw.get(key), str):
                    item[key] = _text(raw[key], 6000 if key in {"rules", "rules_primary", "rules_secondary"} else 500)
            for key in ("probability", "bid", "ask", "last", "volume", "forecaster_count", "price", "yes_bid", "yes_ask", "last_price", "no_bid", "no_ask", "volume_24h", "open_interest", "notional_value", "floor_strike", "cap_strike"):
                val = raw.get(key)
                if val is None:
                    if key in raw:
                        item[key] = None
                elif isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val):
                    item[key] = val if key != "probability" or 0 <= val <= 1 else None
            cutoff = _date(self.as_of, end_of_day=True)
            item["temporal"] = {"publication_time_known": published is not None,
                                "point_in_time_verified": False,
                                "retrieved_after_cutoff": bool(cutoff and _date(item["retrieved_at"]) > cutoff)}
            if isinstance(raw.get("detail_obtained"), bool):
                item["detail_obtained"] = raw["detail_obtained"]
            source_prices = raw.get("source_price_fields")
            if isinstance(source_prices, dict):
                item["source_price_fields"] = self._source_prices(source_prices)
            if not re.fullmatch(r"[a-f0-9]{64}", str(item.get("evidence_sha256", ""))):
                item.pop("evidence_sha256", None)
                item["evidence_sha256"] = hashlib.sha256(_canonical(item)).hexdigest()
            normalized["items"].append(item)
        return normalized

    @staticmethod
    def _source_prices(values):
        result = {}
        for key, value in list(values.items())[:16]:
            if not isinstance(key, str):
                continue
            def scalar(number):
                if number is None or isinstance(number, bool):
                    return None
                if isinstance(number, (int, float)):
                    return number if math.isfinite(number) else None
                return _text(number, 80) if isinstance(number, str) else None
            result[_text(key, 60)] = [scalar(v) for v in value[:8]] if isinstance(value, list) else scalar(value)
        return result

    def record_result(self, provider, query, result):
        """Record a provider-qualified capture; repeated identities replay exactly."""
        if self.artifact_dir is None:
            return self._result(provider, query, "unavailable", reason="artifact_dir_required")
        if not _env_bool("NEWS_CONTEXT_ENABLED", True):
            return self._result(provider, query, "disabled", reason="context_disabled")
        with _locked(self.artifact_dir) as descriptor:
            return self._store(descriptor, self._current(descriptor), provider, query, result)

    def seal(self, *, source_refs=None):
        if self.artifact_dir is None:
            return {}
        existing = load_context(self.artifact_dir, require_sealed=False)
        if not existing and self._bound_generation:
            raise ContextIntegrityError("bound_context_missing")
        if existing:
            self._observe(existing)
        if not _env_bool("NEWS_CONTEXT_ENABLED", True):
            return existing
        with _locked(self.artifact_dir) as descriptor:
            value = self._current(descriptor)
            if value["sealed"]:
                return value
            refs = {url: ref for url, ref in (source_refs or {}).items()
                    if isinstance(url, str) and isinstance(ref, str) and re.fullmatch(r"S[1-9][0-9]*", ref)}
            for item in value["items"] + [item for result in value["queries"] for item in result["items"]]:
                if item["url"] in refs:
                    item["source_ref"] = refs[item["url"]]
            value["sealed"] = True
            _write(descriptor, value)
            self._bound_generation = value["generation_id"]
            self._observe(value)
            return value

    def _spent_seconds(self, value):
        # Older captures did not separate acquisition from idle/model time.
        # Never restore an unknowable spent allowance on an upgrade/restart.
        if "acquisition_seconds" in value:
            return value["acquisition_seconds"]
        counters = value.get("network_requests", {})
        counts = list(counters.values()) if isinstance(counters, dict) else []
        counts.extend(row.get(key) for row in value.get("queries", [])
                      for key in ("request_count", "network_requests"))
        prior_io = value.get("network_started_at") or any(type(count) is int and count > 0 for count in counts)
        return _env_num("NEWS_CONTEXT_DEADLINE_SECONDS", 10, 10) if prior_io else 0

    def _remaining(self, value, deadline):
        cap = _env_num("NEWS_CONTEXT_DEADLINE_SECONDS", 10, 10)
        cap -= self._spent_seconds(value)
        if deadline is not None:
            supplied = float(deadline.remaining()) if hasattr(deadline, "remaining") else float(deadline) - time.monotonic()
            cap = min(cap, supplied) if math.isfinite(supplied) else 0
        return max(0, cap)

    def _search(self, provider, query, deadline):
        query = _query(query)
        enabled = (_env_bool("NEWSAPI_ENABLED", True) if self._news_enabled is None else self._news_enabled) if provider == "newsapi" else (
            _env_bool("REDDIT_SIGNALS_ENABLED", False) if self._social_enabled is None else self._social_enabled)
        if not _env_bool("NEWS_CONTEXT_ENABLED", True) or not enabled:
            return self._result(provider, query, "disabled", reason="provider_disabled")
        if self.artifact_dir is None:
            return self._result(provider, query, "unavailable", reason="artifact_dir_required")
        allowed, reason = _budget("attempt")
        if not allowed:
            return self._result(provider, query, "budget_exhausted", reason=reason or "attempt_budget")
        with _locked(self.artifact_dir, deadline=deadline) as descriptor:
            value = self._current(descriptor)
            request_id = self._request_id(provider, query)
            previous = next((r for r in value["queries"] if r["request_id"] == request_id), None)
            if previous:
                return json.loads(_canonical(previous))
            if value["sealed"]:
                return self._result(provider, query, "unavailable", reason="generation_sealed")
            if not query:
                return self._store(descriptor, value, provider, query, self._result(provider, query, "unavailable", reason="empty_query"))
            if len(value["queries"]) >= MAX_QUERIES:
                return self._result(provider, query, "budget_exhausted", reason="query_limit")
            key = self._api_key if self._api_key is not None else (os.environ.get("NEWSAPI_API_KEY", "") if provider == "newsapi" else "")
            if provider == "newsapi" and not key:
                return self._store(descriptor, value, provider, query, self._result(provider, query, "unavailable", reason="missing_api_key"))
            cap = int(_env_num("NEWSAPI_MAX_REQUESTS", 2, 2)) if provider == "newsapi" else int(_env_num("REDDIT_MAX_REQUESTS", 1, 1))
            if provider == "newsapi" and self._max_news_requests is not None:
                cap = min(cap, max(0, int(self._max_news_requests)))
            calls = value.setdefault("network_requests", {}).get(provider, 0)
            if calls >= cap:
                return self._store(descriptor, value, provider, query, self._result(provider, query, "budget_exhausted", reason="provider_request_limit"))
            remaining = min(self._remaining(value, deadline), _env_num("NEWS_CONTEXT_HTTP_TIMEOUT_SECONDS", 5, 5))
            if remaining <= 0:
                return self._store(descriptor, value, provider, query, self._result(provider, query, "timeout", reason="stage_deadline"))
            allowed, reason = _budget("network")
            if not allowed:
                return self._store(descriptor, value, provider, query, self._result(provider, query, "budget_exhausted", reason=reason or "network_budget"))
            spent = self._spent_seconds(value)
            value["network_requests"][provider] = calls + 1
            value.setdefault("network_started_at", _utcnow())
            # Reserve the full request timeout before dispatch; a dead process
            # cannot return this time to another worker. Settle only on return.
            value["acquisition_seconds"] = spent + remaining
            started = time.monotonic()
            # Reserve before I/O. A crash replays this interrupted capture and cannot refetch.
            pending = self._store(descriptor, value, provider, query, self._result(provider, query, "unavailable", True, "capture_interrupted"))
            timeout = min(remaining - (time.monotonic() - started),
                          self._remaining({"acquisition_seconds": spent}, deadline))
            try:
                result = (self._acquire(provider, query, key, timeout) if timeout > 0 else
                          self._result(provider, query, "timeout", reason="stage_deadline"))
                if timeout > 0 and time.monotonic() > started + remaining:
                    result = self._result(provider, query, "timeout", True, "http_deadline")
            except TimeoutError:
                result = self._result(provider, query, "timeout", True, "transport_timeout")
            except Exception:
                result = self._result(provider, query, "unavailable", True, "transport_error")
            value["acquisition_seconds"] = spent + max(0, time.monotonic() - started)
            value["queries"] = [r for r in value["queries"] if r["request_id"] != pending["request_id"]]
            return self._store(descriptor, value, provider, query, result)

    def _acquire(self, provider, query, key, timeout):
        headers = {"Accept": "application/json", "User-Agent": "DeepResearchForecast-context/1"}
        cutoff = _date(self.as_of, end_of_day=True) or datetime.now(timezone.utc)
        start = cutoff - timedelta(days=int(_env_num("NEWSAPI_LOOKBACK_DAYS", 30, 30)))
        if provider == "newsapi":
            headers["X-Api-Key"] = key
            params = {"q": query, "language": self.language, "from": start.isoformat(), "to": cutoff.isoformat(),
                      "pageSize": max(1, int(_env_num("NEWSAPI_PAGE_SIZE", 20, 20))), "page": 1, "sortBy": "publishedAt"}
            url = "https://newsapi.org/v2/everything?" + urlencode(params)
        else:
            url = "https://www.reddit.com/search.json?" + urlencode({"q": query, "limit": 20, "sort": "new", "t": "month", "raw_json": 1})
        if timeout <= 0:
            return self._result(provider, query, "timeout", reason="http_deadline")
        code, raw = self._transport(url, headers=headers, timeout=timeout, max_bytes=MAX_RESPONSE_BYTES)
        state = {401: "forbidden", 403: "forbidden", 429: "rate_limited"}.get(code)
        if state or code != 200:
            return self._result(provider, query, state or "unavailable", True, "http_" + str(int(code)), http_status=int(code))
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
            return self._result(provider, query, "unavailable", True, "response_too_large")
        if key:
            raw = raw.replace(str(key).encode("utf-8"), b"[redacted]")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            return self._result(provider, query, "unavailable", True, "invalid_json")
        if not isinstance(payload, dict):
            return self._result(provider, query, "unavailable", True, "invalid_response")
        if provider == "newsapi":
            rows = payload.get("articles")
            if payload.get("status") != "ok" or not isinstance(rows, list):
                return self._result(provider, query, "unavailable", True, "invalid_response")
        else:
            data = payload.get("data")
            rows = data.get("children") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                return self._result(provider, query, "unavailable", True, "invalid_response")
        items, seen, discarded, unknown = [], set(), 0, 0
        page_size = max(1, int(_env_num("NEWSAPI_PAGE_SIZE", 20, 20))) if provider == "newsapi" else 20
        for entry in rows[:page_size]:
            row = entry if provider == "newsapi" else entry.get("data") if isinstance(entry, dict) else None
            if not isinstance(row, dict):
                discarded += 1
                continue
            if provider == "newsapi":
                published = _date(row.get("publishedAt"))
                native = None
                source = row.get("source") if isinstance(row.get("source"), dict) else {}
                publisher = _text(source.get("name"), 200)
                link = _url(row.get("url"))
                snippet = row.get("description")
            else:
                try:
                    published = datetime.fromtimestamp(float(row["created_utc"]), timezone.utc)
                except (ValueError, TypeError, KeyError, OverflowError, OSError):
                    published = None
                native = _text(row.get("name") or row.get("id"), 100)
                publisher = _text(row.get("subreddit"), 200)
                permalink = row.get("permalink")
                link = _url("https://www.reddit.com" + permalink) if isinstance(permalink, str) and permalink.startswith("/r/") else ""
                snippet = row.get("selftext")
            title = _text(row.get("title"), 500)
            repeated = (title.casefold(), publisher.casefold())
            if not title or not link or link in seen or repeated in seen or (published and (published > cutoff or published < start or published > datetime.now(timezone.utc))):
                discarded += 1
                continue
            seen.update((link, repeated))
            if published is None:
                unknown += 1
            item = {"id": native or hashlib.sha256(link.encode()).hexdigest(), "provider": provider,
                    "kind": "news_snippet" if provider == "newsapi" else "social_post", "title": title,
                    "url": link, "published_at": published.isoformat() if published else None,
                    "language": self.language, "snippet": _text(snippet, 1600),
                    "publisher": publisher, "native_id": native or link}
            if provider == "newsapi":
                item["publisher_id"] = _text(source.get("id"), 200)
            if provider == "reddit":
                item["subreddit"] = publisher
            items.append(item)
        state = "ok" if items else "verified_empty" if not rows else "partial"
        if items and (discarded or unknown):
            state = "partial"
        result = self._result(provider, query, state, True, items=items,
                              method="newsapi-everything-v1" if provider == "newsapi" else "reddit-search-v1",
                              coverage="One bounded page; provider plan delay and coverage may apply. Publication date alone does not establish historical availability.",
                              discarded=discarded, **{"from": start.isoformat(), "to": cutoff.isoformat()})
        result["status"]["unknown_publication_dates"] = unknown
        result["status"]["returned"] = len(items)
        return result

    def search_news(self, query, *, deadline=None):
        try:
            return self._search("newsapi", query, deadline)
        except TimeoutError:
            return self._result("newsapi", query, "timeout", reason="context_lock_timeout")

    def search_social(self, query, *, deadline=None):
        try:
            return self._search("reddit", query, deadline)
        except TimeoutError:
            return self._result("reddit", query, "timeout", reason="context_lock_timeout")

    def capture_market(self, provider, query, acquire, *, deadline=None):
        """Capture an external provider while durably reserving every HTTP call.

        ``acquire(reserve_network)`` runs under the same cross-process store lock.
        The zero-argument reservation callback returns ``allowed/state/reason``;
        adapters MUST call it immediately before each physical request and honor
        denials. Reservation counts survive a crash before result persistence.
        """
        if provider not in {"polymarket", "kalshi", "metaculus"}:
            raise ValueError("invalid_external_provider")
        query = _query(query)
        if not _env_bool("NEWS_CONTEXT_ENABLED", True) or not _env_bool("MARKET_INTELLIGENCE_ENABLED", True):
            return self._result(provider, query, "disabled", reason="comparison_disabled")
        if self.artifact_dir is None:
            return self._result(provider, query, "unavailable", reason="artifact_dir_required")
        allowed, reason = _budget("attempt")
        if not allowed:
            return self._result(provider, query, "budget_exhausted", reason=reason or "attempt_budget")
        try:
            with _locked(self.artifact_dir, deadline=deadline) as descriptor:
                value = self._current(descriptor)
                request_id = self._request_id(provider, query)
                previous = next((row for row in value["queries"] if row["request_id"] == request_id), None)
                if previous is not None:
                    return json.loads(_canonical(previous))
                if value["sealed"]:
                    return self._result(provider, query, "unavailable", reason="generation_sealed")
                if len(value["queries"]) >= MAX_QUERIES:
                    return self._result(provider, query, "budget_exhausted", reason="query_limit", request_count=0)
                if not query:
                    return self._store(descriptor, value, provider, query, self._result(provider, query, "unsupported", reason="empty_query"))
                counters = value.setdefault("network_requests", {})
                # A capture may carry an old adapter count, a durable reservation
                # count, or both. They describe the same requests, so use the
                # larger valid count per capture, then reconcile with the shared
                # high-water mark; never add these overlapping representations.
                def valid_count(count):
                    return count if type(count) is int and count >= 0 else 0
                spent = sum(max(valid_count(row.get("request_count")),
                                valid_count(row.get("network_requests")))
                            for row in value["queries"]
                            if row["provider"] in {"polymarket", "kalshi", "metaculus"})
                persisted = counters.get("market", 0)
                if type(persisted) is not int or persisted < 0:
                    raise ContextIntegrityError("invalid_market_counter")
                counters["market"] = max(persisted, spent)
                cap = int(_env_num("MARKET_INTELLIGENCE_MAX_REQUESTS", 4, 4))
                remaining = self._remaining(value, deadline)
                if counters["market"] >= cap:
                    return self._store(descriptor, value, provider, query, self._result(provider, query, "budget_exhausted", reason="market_request_limit", request_count=0))
                if remaining <= 0:
                    return self._store(descriptor, value, provider, query, self._result(provider, query, "timeout", reason="stage_deadline", request_count=0))
                spent = self._spent_seconds(value)
                # The callback may perform multiple HTTP calls. Reserve its
                # entire residual allowance until it returns under this lock.
                value["acquisition_seconds"] = spent + remaining
                started = time.monotonic()
                self._store(descriptor, value, provider, query,
                            self._result(provider, query, "unavailable", reason="capture_interrupted", request_count=0))
                pending = next(row for row in value["queries"] if row["request_id"] == request_id)
                reserved = 0
                last_denial = None
                end = started + remaining

                def reserve_request():
                    nonlocal reserved, last_denial
                    # The durable reservation belongs to this active callback;
                    # its local deadline already bounds the reserved time.
                    caller_remaining = self._remaining({"acquisition_seconds": spent}, deadline)
                    request_end = min(end, time.monotonic() + caller_remaining)
                    if time.monotonic() >= request_end:
                        last_denial = {"allowed": False, "state": "timeout", "reason": "stage_deadline"}
                    elif counters["market"] >= cap:
                        last_denial = {"allowed": False, "state": "budget_exhausted", "reason": "market_request_limit"}
                    else:
                        admitted, why = _budget("network")
                        if not admitted:
                            last_denial = {"allowed": False, "state": "budget_exhausted", "reason": why or "network_budget"}
                        else:
                            counters["market"] += 1
                            reserved += 1
                            value.setdefault("network_started_at", _utcnow())
                            pending["request_count"] = reserved
                            pending["status"]["attempted"] = True
                            value["providers"][provider] = pending["status"].copy()
                            _write(descriptor, value)
                            return {"allowed": True, "state": "ok", "reason": "", "deadline": request_end}
                    return dict(last_denial)

                try:
                    result = acquire(reserve_request)
                    if not isinstance(result, dict):
                        raise ValueError("invalid_external_result")
                except Exception:
                    result = self._result(provider, query, "unavailable", reserved > 0, "capture_failed")
                if time.monotonic() > end:
                    result = self._result(provider, query, "timeout", reserved > 0, "stage_deadline")
                elif last_denial and not result.get("items"):
                    result = self._result(provider, query, last_denial["state"], reserved > 0, last_denial["reason"])
                elif last_denial:
                    result = dict(result, status={"state": "partial", "attempted": reserved > 0, "reason": last_denial["reason"]})
                # A callback cannot underreport or invent physical admissions.
                result = dict(result)
                result["request_count"] = reserved
                result["status"] = dict(result.get("status", {}), attempted=reserved > 0)
                value["acquisition_seconds"] = spent + max(0, time.monotonic() - started)
                value["queries"] = [row for row in value["queries"] if row["request_id"] != request_id]
                return self._store(descriptor, value, provider, query, result)
        except TimeoutError:
            return self._result(provider, query, "timeout", reason="context_lock_timeout")

    def market_compare(self, query, *, deadline=None):
        if self.artifact_dir is None:
            return self._result("polymarket", query, "unavailable", reason="artifact_dir_required")
        if not _env_bool("NEWS_CONTEXT_ENABLED", True) or not _env_bool("MARKET_INTELLIGENCE_ENABLED", True):
            return self._result("polymarket", query, "disabled", reason="comparison_disabled")
        if __package__:
            from .market_intelligence import compare_markets
        else:
            from market_intelligence import compare_markets
        return compare_markets(self, query, deadline=deadline)


def get_context_client(artifact_dir=None, *, question=None, language=None, as_of=None):
    """Get the trusted run client. None identity fields preserve an existing binding."""
    root = _root_path(artifact_dir if artifact_dir is not None else os.environ.get("DEERFLOW_RUN_ARTIFACT_DIR"))
    if root is None:
        return ContextClient(None, question=question, language=language, as_of=as_of)
    # Use the same root -> cache ordering as capture retirement. Never hold the
    # global registry lock while snapshot() waits for a root/file lock: a
    # concurrent archiver holds that root while retiring its cache registration.
    lock = _thread_lock(root)
    if not lock.acquire(timeout=_env_num("NEWS_CONTEXT_DEADLINE_SECONDS", 10, 10)):
        raise TimeoutError("context_cache_lock_timeout")
    try:
        with _CACHE_LOCK:
            client = _CLIENTS.get(str(root))
        if client is not None:
            candidate = {"question_sha256": _question_hash(question) if question is not None or "NEWS_CONTEXT_QUESTION_SHA256" in os.environ else client.question_sha256,
                         "language": _language(language) if language is not None else client.language,
                         "as_of": _identity_date(as_of) if as_of is not None else client.as_of}
            client._check_identity(candidate)
            client.snapshot()  # Detect present tampering even when the process cache is warm.
            return client
        client = ContextClient(root, question=question, language=language, as_of=as_of)
        with _CACHE_LOCK:
            _CLIENTS[str(root)] = client
        return client
    finally:
        lock.release()


def merge_contexts(input_dirs, output_dir):
    """Deterministic sealed merge; lane-local citations must be remapped at final seal."""
    contexts = [context for directory in input_dirs if (context := load_context(directory))]
    if not contexts:
        return {}
    contexts.sort(key=lambda row: (row["generation_id"], row["sha256"]))
    first = contexts[0]
    if any(any(row[key] != first[key] for key in ("question_sha256", "language", "as_of")) for row in contexts):
        raise ContextIntegrityError("merge_identity_mismatch")
    merged = {key: first[key] for key in ("schema_version", "question_sha256", "language", "as_of", "created_at")}
    merged.update({"generation_id": hashlib.sha256(_canonical(sorted({row["sha256"] for row in contexts}))).hexdigest(),
                   "sealed": True, "providers": {}, "queries": [], "items": [],
                   "input_generations": sorted({row["generation_id"] for row in contexts})})
    query_seen, item_seen = set(), set()
    for context in contexts:
        merged["providers"].update(context["providers"])
        for original in context["queries"]:
            row = json.loads(_canonical(original))
            key = (row["provider"], row.get("capture_id", context["generation_id"]), row["request_id"])
            if key in query_seen:
                continue
            query_seen.add(key)
            for item in row["items"]:
                item.pop("source_ref", None)
            merged["queries"].append(row)
        for original in context["items"]:
            row = json.loads(_canonical(original))
            key = (row["provider"], row["id"], row.get("capture_id", context["generation_id"]))
            if key not in item_seen:
                row.pop("source_ref", None)
                merged["items"].append(row)
                item_seen.add(key)
    if len(merged["queries"]) > MAX_QUERIES or len(merged["items"]) > MAX_ITEMS:
        raise ContextIntegrityError("merge_exceeds_limits")
    root = _root_path(output_dir)
    if root is None:
        raise ContextIntegrityError("artifact_dir_required")
    with _locked(root) as descriptor:
        existing = _read(descriptor, require_sealed=False)
        merged["sha256"] = _digest(merged)
        if existing and existing != merged:
            raise ContextIntegrityError("merge_output_already_bound")
        if not existing:
            _write(descriptor, merged)
    return merged


def _markdown(value, limit=300):
    text = _text(value, limit)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()|#!])", r"\\\1", text)


def _market_details(row):
    def shown(value, limit=180):
        if value is None or value == "":
            return "unknown"
        if isinstance(value, bool):
            return "unknown"
        if isinstance(value, (int, float)):
            return format(value, ".12g") if math.isfinite(value) else "unknown"
        return _markdown(value, limit)
    fields = []
    if row.get("kind") == "market_quote":
        fields.extend([
            "outcome=" + shown(row.get("outcome")) + "; Yes=" + shown(row.get("yes_label")) + "; No=" + shown(row.get("no_label")),
            "indicative price=" + shown(row.get("probability")) + "; bid=" + shown(row.get("bid", row.get("yes_bid")))
            + "; ask=" + shown(row.get("ask", row.get("yes_ask"))) + "; last=" + shown(row.get("last", row.get("last_price"))),
            "basis=" + shown(row.get("probability_basis") or row.get("price_basis") or row.get("quote_basis"))
            + "; units=" + shown(row.get("price_unit") or row.get("quote_units") or row.get("units")),
            "quote time=" + shown(row.get("quote_at") or row.get("quote_time")),
            "volume=" + shown(row.get("volume")) + " " + shown(row.get("volume_unit") or row.get("volume_units")),
            "horizon=" + shown(row.get("end_date")) + "; strike=" + shown(row.get("strike_type"))
            + "; floor=" + shown(row.get("floor_strike")) + "; cap=" + shown(row.get("cap_strike")),
            "rules=" + shown(row.get("rules_primary") or row.get("rules"), 600)
            + "; secondary rules=" + shown(row.get("rules_secondary"), 300),
        ])
    elif row.get("kind") == "community_forecast":
        fields.extend(["outcome=" + shown(row.get("outcome")), "forecast=" + shown(row.get("probability")),
                       "basis=" + shown(row.get("probability_basis") or row.get("price_basis")),
                       "forecasters=" + shown(row.get("forecaster_count")), "horizon=" + shown(row.get("end_date"))])
    return "; ".join(fields)


def render_context(context, *, lang="en", max_items=12):
    """Render bounded untrusted source text with contextual provenance, never anchors."""
    if not context:
        return ""
    # The engine may add lane-local citation references to a presentation copy.
    # Durable proof is verified by load_context/seal; rendering validates schema.
    _validate(context, require_sealed=False, verify_digest=False)
    chinese = _language(lang) == "zh"
    lines = ["### 新闻与市场背景" if chinese else "### News and market context",
             ("仅供背景参考；不是概率锚点或结算证据。新闻摘要尚未获取全文；发布日期不能证明历史时点可得性。" if chinese else
              "Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability."),
             "", "| Provider / kind | Source | Published / retrieved | Status / captured contract |",
             "| --- | --- | --- | --- |"]
    for provider, status in sorted(context["providers"].items()):
        if isinstance(status, dict):
            lines.append(f"| {_markdown(provider)} | — | — | {_markdown(status.get('state', 'unavailable'))} ({_markdown(status.get('reason', ''))}) |")
    for row in context["items"][:max(0, min(20, int(max_items)))]:
        link = _url(row["url"])
        # Encode Markdown delimiters in a validated URL; text is escaped separately.
        link = link.replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E").replace(" ", "%20").replace("|", "%7C").replace("\\", "%5C")
        source_ref = " " + _markdown(row["source_ref"]) if row.get("source_ref") else ""
        details = _market_details(row)
        status = "context_only" + ("; " + details if details else "")
        lines.append(f"| {_markdown(row['provider'])} / {row['kind']} | [{_markdown(row['title'])}]({link}){source_ref} | {_markdown(row.get('published_at') or 'unknown')} / {_markdown(row.get('retrieved_at') or 'unknown')} | {status} |")
    return "\n".join(lines)[:24000]
