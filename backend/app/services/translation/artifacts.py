"""Immutable admitted document generations, independent of the coordination DB.

Adapters perform semantic admission. This module seals their exact bytes and
switches one pointer only after source and worker ownership checks under the
publication lock. Lock order: operation fence, artifact lock, pointer replace.
Readers never initialize a scheduler, import a provider, or repair a publication.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Callable


class ArtifactError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path) -> str | None:
    try:
        return digest(Path(path).read_bytes())
    except OSError:
        return None


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _component(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ArtifactError("invalid_artifact_identity", "Invalid artifact identity", 400)
    return value


def _store(root, kind, lang) -> Path:
    return Path(root) / ".translation-artifacts" / _component(kind) / _component(lang)


def image_references(markdown):
    """Resolved Markdown destinations, including references/titles, excluding code."""
    from ..model_translation import _parse
    tokens, _ = _parse(markdown)
    result = []
    def visit(items):
        for token in items:
            if token.get("type") == "image":
                value = (token.get("attrs") or {}).get("url")
                if isinstance(value, str):
                    result.append(value)
            visit(token.get("children") or [])
    visit(tokens)
    return result


def figure_inventory(markdown, source_path):
    """Bind local rendered figures using the same parser as receipt admission."""
    from urllib.parse import unquote, urlsplit
    folder = Path(source_path).resolve().parent
    result = {}
    for reference in image_references(markdown):
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ArtifactError("invalid_figure", "Published figures must be local document assets", 422)
        path = Path(unquote(parsed.path))
        if not path.is_absolute():
            path = folder / path
        if not path.resolve().is_relative_to(folder) or path.is_symlink() or not path.is_file():
            raise ArtifactError("invalid_figure", "Published figure is missing or outside the document", 422)
        relative = path.resolve().relative_to(folder).as_posix()
        value = file_digest(path)
        if value is None:
            raise ArtifactError("invalid_figure", "Published figure is unreadable", 422)
        result[relative] = value
    return result


def _check_figures(markdown, source_path, assets):
    raw = assets.get("figures.json")
    if raw is None:
        raise ArtifactError("invalid_artifact", "Publication has no figure dependency inventory")
    try:
        expected = json.loads(raw) if isinstance(raw, bytes) else raw
        actual = figure_inventory(markdown, source_path)
    except ArtifactError as exc:
        raise ArtifactError("stale_artifact", "Published figure dependencies are unavailable") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise ArtifactError("stale_artifact", "Published figure dependencies are unavailable") from exc
    if actual != expected:
        raise ArtifactError("stale_artifact", "Published figure bytes changed; reload the document")


def atomic_bytes(path, value: bytes):
    """Replace one file after flushing its bytes; no power-loss claim is made."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".stage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def artifact_lock(path, *, blocking=True):
    """OS ownership lock; never silently fall back to an unlocked publication."""
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise ArtifactError("artifact_busy", "This artifact is already being generated; retry shortly") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


_owner_check: ContextVar[Callable | None] = ContextVar("translation_publication_owner", default=None)


@contextmanager
def publication_fence(check: Callable):
    """Scheduler binds its durable operation fence around a named handler.

The callback must raise if cancelled or superseded. It runs inside the artifact
lock immediately before pointer replacement, as well as before staging.
"""
    token = _owner_check.set(check)
    try:
        yield
    finally:
        _owner_check.reset(token)


@dataclass(frozen=True)
class ArtifactSnapshot:
    root: str
    kind: str
    ref_id: str
    lang: str
    generation: str
    source_sha256: str
    markdown: str
    audit: dict
    assets: dict[str, bytes]
    path: str

    @property
    def markdown_sha256(self):
        return digest(self.markdown.encode("utf-8"))


def resolve_generation(root, *, kind, ref_id, lang, source_sha256, source_path=None):
    """Resolve exactly one sealed generation. None means no v2 pointer exists.

    A stale/corrupt v2 pointer is an error, never permission to fall back to a
    different legacy body. Legacy admission is the owning adapter's responsibility.
    """
    base = _store(root, kind, lang)
    pointer = base / "current.json"
    if not pointer.exists():
        return None
    try:
        selected = json.loads(pointer.read_bytes())
        generation = selected["generation"]
        if not re.fullmatch(r"[a-f0-9]{64}", generation):
            raise ValueError("invalid generation")
        folder = base / "generations" / generation
        raw_manifest = (folder / "manifest.json").read_bytes()
        if digest(raw_manifest) != generation:
            raise ValueError("manifest digest mismatch")
        manifest = json.loads(raw_manifest)
        if any(manifest.get(key) != val for key, val in {
            "schema": "translation-artifact/v2", "kind": kind, "ref_id": ref_id,
            "lang": lang, "source_sha256": source_sha256,
        }.items()):
            raise ArtifactError("stale_artifact", "Published translation belongs to another source or identity")
        files = {}
        for name, sha in manifest["files"].items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in {".", ".."}:
                raise ValueError("invalid asset name")
            file = folder / name
            if file.is_symlink():
                raise ValueError("symlink asset")
            data = file.read_bytes()
            if digest(data) != sha:
                raise ValueError("asset digest mismatch")
            files[name] = data
        markdown = files.pop("document.md").decode("utf-8")
        audit = json.loads(files.pop("audit.json"))
        if (audit.get("hard_passed") is not True
                or audit.get("markdown_sha256") != digest(markdown.encode("utf-8"))
                or audit.get("source_markdown_sha256") != source_sha256):
            raise ValueError("audit admission mismatch")
        if source_path and file_digest(source_path) != source_sha256:
            raise ArtifactError("stale_artifact", "Canonical source changed; reload the document")
        if source_path:
            _check_figures(markdown, source_path, files)
        return ArtifactSnapshot(str(root), kind, ref_id, lang, generation, source_sha256,
                                markdown, audit, files, str(folder))
    except ArtifactError:
        raise
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise ArtifactError("invalid_artifact", "Published translation manifest is invalid") from exc


def assert_current(snapshot: ArtifactSnapshot, source_path):
    current = resolve_generation(snapshot.root, kind=snapshot.kind, ref_id=snapshot.ref_id,
                                 lang=snapshot.lang, source_sha256=snapshot.source_sha256,
                                 source_path=source_path)
    if current is None or current.generation != snapshot.generation:
        raise ArtifactError("stale_artifact", "Selected translation changed; reload before exporting")


def publish_generation(root, *, kind, ref_id, lang, source_sha256, markdown, audit,
                       source_path, assets=None, check_owner=None):
    """Stage a deterministic generation, record intent, then atomically select it.

    A crash before pointer replacement leaves the old publication. A crash after
    it leaves a fully readable generation even before operation completion is
    persisted. Repeating publication of those exact bytes is idempotent.
    """
    if (not markdown.strip() or audit.get("hard_passed") is not True
            or audit.get("markdown_sha256") != digest(markdown.encode("utf-8"))
            or audit.get("source_markdown_sha256") != source_sha256):
        raise ArtifactError("publication_rejected", "Translation has not passed exact-byte admission")
    base = _store(root, kind, lang)
    files = {"document.md": markdown.encode("utf-8"), "audit.json": _json(audit)}
    assets = dict(assets or {})
    assets.setdefault("figures.json", _json(figure_inventory(markdown, source_path)))
    for name, value in assets.items():
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in files
                or name in {".", "..", "manifest.json"}):
            raise ArtifactError("invalid_artifact", "Invalid publication asset name", 400)
        files[name] = value if isinstance(value, bytes) else _json(value)
    manifest = _json({"schema": "translation-artifact/v2", "kind": kind, "ref_id": ref_id,
                      "lang": lang, "source_sha256": source_sha256,
                      "files": {name: digest(value) for name, value in files.items()}})
    generation = digest(manifest)
    checker = check_owner or _owner_check.get()

    def check():
        if checker:
            checker()
        if file_digest(source_path) != source_sha256:
            raise ArtifactError("stale_artifact", "Canonical source changed during translation")
        _check_figures(markdown, source_path, assets)

    with artifact_lock(base / "publication.lock"):
        check()
        generations = base / "generations"
        generations.mkdir(exist_ok=True)
        destination = generations / generation
        if not destination.exists():
            stage = Path(tempfile.mkdtemp(prefix=".generation-", dir=generations))
            try:
                for name, value in {**files, "manifest.json": manifest}.items():
                    atomic_bytes(stage / name, value)
                os.replace(stage, destination)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        else:
            for name, value in {**files, "manifest.json": manifest}.items():
                if (destination / name).read_bytes() != value:
                    raise ArtifactError("invalid_artifact", "Existing immutable generation was modified")
        atomic_bytes(base / "intent.json", _json({"generation": generation, "source_sha256": source_sha256}))
        from .scheduler import publication_guard
        # Cancellation shares this short guard; no provider call or staging occurs in it.
        with publication_guard():
            check()
            atomic_bytes(base / "current.json", _json({"generation": generation}))
    return resolve_generation(root, kind=kind, ref_id=ref_id, lang=lang,
                              source_sha256=source_sha256, source_path=source_path)
