#!/usr/bin/env python3
"""Authoritative, deterministic deployment for DeepResearchForecast skills.

The bridge skill tree owns a small set of runtime bundles layered onto DeerFlow's
larger built-in ``skills/public`` tree.  This module mirrors those owned bundles
without mutating unrelated upstream skills:

* every source bundle is described by a deterministic content manifest;
* writers serialize through a POSIX cross-process lock;
* a complete candidate ``skills/public`` tree is staged and verified first;
* the complete public tree is atomically exchanged on Linux/macOS;
* previously managed names absent from the source are pruned;
* destination-only files inside managed bundles are pruned; and
* the installed manifest is persisted for runtime provenance verification.

There is deliberately no runtime-generated-content allowlist inside a managed
bundle.  Python bytecode, ``.DS_Store``, and similar cache files are disposable
and must never make the executable skill identity ambiguous.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence


SCHEMA_VERSION = 1
STATE_FILENAME = ".drf-runtime-skill-manifest.json"
LOCK_FILENAME = ".drf-runtime-skill-sync.lock"
STAGE_PREFIX = ".drf-public-stage-"

# All six bundles participate in the current research workflow.  Callers may
# pass a narrower explicit set for isolated tests or future mode-specific use.
DEFAULT_REQUIRED_SKILLS: tuple[str, ...] = (
    "actor-ontology-research",
    "data-sources",
    "data-visuals",
    "deep-research",
    "forecast-visuals",
    "prediction-markets",
)

# No generated file is required for a managed skill to execute.  Keeping this
# explicit and empty is safer than retaining stale bytecode or ad-hoc state.
RUNTIME_GENERATED_ALLOWLIST: tuple[str, ...] = ()

# ``skills/public`` is conventionally a directory-of-directories.  Root cache
# files such as .DS_Store are not runtime inputs and are intentionally pruned.
PUBLIC_ROOT_FILE_ALLOWLIST: tuple[str, ...] = ()

_SAFE_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Directory names that are never skill content: bytecode caches, plus the
# ``logs/`` and ``.claude/`` trees that agent-session hooks create in whatever
# directory a shell happened to run in (they hold session transcripts and must
# never be deployed into the runtime skill bundle).
_SOURCE_NOISE_DIRNAMES = {"__pycache__", "logs", ".claude"}
_SOURCE_NOISE_FILENAMES = {".DS_Store"}
_SOURCE_NOISE_SUFFIXES = {".pyc", ".pyo"}


class SkillSyncError(RuntimeError):
    """The authoritative runtime skill deployment could not be proven."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_skill_name(name: str) -> str:
    if not isinstance(name, str) or not _SAFE_SKILL_NAME.fullmatch(name):
        raise SkillSyncError(f"unsafe runtime skill name: {name!r}")
    return name


def _is_source_noise(relative_path: Path) -> bool:
    return (
        any(part in _SOURCE_NOISE_DIRNAMES for part in relative_path.parts)
        or relative_path.name in _SOURCE_NOISE_FILENAMES
        or relative_path.suffix in _SOURCE_NOISE_SUFFIXES
    )


def _build_skill_manifest(
    skill_root: Path,
    skill_name: str,
    *,
    source: bool,
) -> dict[str, Any]:
    """Hash one exact skill directory, including every bundled lazy resource."""

    _validate_skill_name(skill_name)
    if not skill_root.is_dir() or skill_root.is_symlink():
        raise SkillSyncError(f"runtime skill directory is missing or unsafe: {skill_root}")

    directories: list[str] = []
    files: list[dict[str, Any]] = []
    for current, dir_names, file_names in os.walk(skill_root, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(skill_root)
        kept_dirs: list[str] = []
        for name in sorted(dir_names):
            path = current_path / name
            relative = relative_current / name
            if source and _is_source_noise(relative):
                continue
            if path.is_symlink():
                raise SkillSyncError(f"symlink is not allowed in runtime skill bundle: {path}")
            kept_dirs.append(name)
            directories.append(relative.as_posix())
        dir_names[:] = kept_dirs

        for name in sorted(file_names):
            path = current_path / name
            relative = relative_current / name
            if source and _is_source_noise(relative):
                continue
            if path.is_symlink() or not path.is_file():
                raise SkillSyncError(f"non-regular runtime skill resource: {path}")
            files.append({
                "path": relative.as_posix(),
                "sha256": _sha256_file(path),
                "size": path.stat().st_size,
            })

    directories.sort()
    files.sort(key=lambda entry: entry["path"])
    skill_rows = [entry for entry in files if entry["path"] == "SKILL.md"]
    if len(skill_rows) != 1:
        raise SkillSyncError(f"{skill_name}: required SKILL.md is missing")

    core = {
        "schema_version": SCHEMA_VERSION,
        "skill": skill_name,
        "directories": directories,
        "files": files,
    }
    lazy_resource_hashes = {
        entry["path"]: entry["sha256"]
        for entry in files
        if entry["path"] != "SKILL.md"
    }
    return {
        **core,
        "manifest_hash": _sha256_bytes(_canonical_bytes(core)),
        "skill_md_sha256": skill_rows[0]["sha256"],
        "lazy_resource_hashes": lazy_resource_hashes,
    }


def _discover_source_manifests(source_root: Path) -> dict[str, dict[str, Any]]:
    if not source_root.is_dir() or source_root.is_symlink():
        raise SkillSyncError(f"runtime skill source root is missing or unsafe: {source_root}")

    manifests: dict[str, dict[str, Any]] = {}
    for candidate in sorted(source_root.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        skill_file = candidate / "SKILL.md"
        if not skill_file.is_file() or skill_file.is_symlink():
            continue
        name = _validate_skill_name(candidate.name)
        manifests[name] = _build_skill_manifest(candidate, name, source=True)
    return manifests


def _bundle_manifest_hash(manifests: Mapping[str, Mapping[str, Any]]) -> str:
    core = {
        "schema_version": SCHEMA_VERSION,
        "skills": {
            name: manifest["manifest_hash"]
            for name, manifest in sorted(manifests.items())
        },
    }
    return _sha256_bytes(_canonical_bytes(core))


def _state_payload(manifests: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "managed_by": "DeepResearchForecast",
        "managed_skills": sorted(manifests),
        "bundle_manifest_hash": _bundle_manifest_hash(manifests),
        "runtime_generated_allowlist": list(RUNTIME_GENERATED_ALLOWLIST),
        "public_root_file_allowlist": list(PUBLIC_ROOT_FILE_ALLOWLIST),
        "skills": {
            name: dict(manifest)
            for name, manifest in sorted(manifests.items())
        },
    }


def _load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise SkillSyncError(f"runtime skill state path is unsafe: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SkillSyncError(f"runtime skill state is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise SkillSyncError("runtime skill state must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SkillSyncError("runtime skill state schema is unsupported")
    if payload.get("managed_by") != "DeepResearchForecast":
        raise SkillSyncError("runtime skill state owner is invalid")
    names = payload.get("managed_skills")
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise SkillSyncError("runtime skill state managed_skills is invalid")
    for name in names:
        _validate_skill_name(name)
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: float) -> Iterator[None]:
    """Acquire a process-wide advisory lock with a bounded wait."""

    if timeout_seconds < 0:
        raise SkillSyncError("runtime skill lock timeout must be non-negative")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise SkillSyncError(
                        f"timed out waiting for runtime skill sync lock: {path}"
                    ) from exc
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _copy_source_bundle(
    source_root: Path,
    stage_root: Path,
    manifest: Mapping[str, Any],
) -> None:
    name = str(manifest["skill"])
    destination = stage_root / name
    destination.mkdir(parents=True, exist_ok=False)
    for relative in manifest["directories"]:
        (destination / relative).mkdir(parents=True, exist_ok=True)
    for entry in manifest["files"]:
        source = source_root / name / entry["path"]
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _copy_unmanaged_public_skills(
    deployed_public_root: Path,
    stage_root: Path,
    managed_names: set[str],
) -> None:
    if not deployed_public_root.exists():
        return
    if not deployed_public_root.is_dir() or deployed_public_root.is_symlink():
        raise SkillSyncError(
            f"deployed skills/public path is missing or unsafe: {deployed_public_root}"
        )

    for entry in sorted(deployed_public_root.iterdir(), key=lambda path: path.name):
        if entry.name == STATE_FILENAME or entry.name in managed_names:
            continue
        target = stage_root / entry.name
        if entry.is_symlink():
            # Unmanaged upstream skills are outside this mirror's authority.  If
            # the vendor uses a top-level symlink, preserve the link itself.
            os.symlink(os.readlink(entry), target, target_is_directory=entry.is_dir())
        elif entry.is_dir():
            shutil.copytree(entry, target, symlinks=True, copy_function=shutil.copy2)
        elif entry.is_file() and entry.name in PUBLIC_ROOT_FILE_ALLOWLIST:
            shutil.copy2(entry, target)


def _atomic_exchange(left: Path, right: Path) -> None:
    """Atomically swap two existing directories on supported POSIX platforms."""

    libc = ctypes.CDLL(None, use_errno=True)
    left_raw = os.fsencode(left)
    right_raw = os.fsencode(right)
    ctypes.set_errno(0)
    if sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise SkillSyncError("atomic directory exchange is unavailable on this macOS runtime")
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(left_raw, right_raw, 0x00000002)  # RENAME_SWAP
    elif sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise SkillSyncError("atomic directory exchange requires libc renameat2")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, left_raw, -100, right_raw, 0x00000002)  # RENAME_EXCHANGE
    else:
        raise SkillSyncError(
            f"atomic runtime skill deployment is unsupported on {sys.platform!r}"
        )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise SkillSyncError(
            "atomic runtime skill directory exchange failed: "
            f"{os.strerror(error_number)}"
        )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _deployed_manifests(
    deployed_public_root: Path,
    names: Iterable[str],
) -> dict[str, dict[str, Any]]:
    return {
        name: _build_skill_manifest(
            deployed_public_root / name,
            name,
            source=False,
        )
        for name in sorted(names)
    }


def _result_payload(
    *,
    outcome: str,
    deployed_public_root: Path,
    source_manifests: Mapping[str, Mapping[str, Any]],
    deployed_manifest_hash: str,
    pruned_skills: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "outcome": outcome,
        "source_manifest_hash": _bundle_manifest_hash(source_manifests),
        "deployed_manifest_hash": deployed_manifest_hash,
        "deployed_path": str(deployed_public_root.resolve(strict=False)),
        "managed_skills": sorted(source_manifests),
        "pruned_skills": sorted(pruned_skills),
        "runtime_generated_allowlist": list(RUNTIME_GENERATED_ALLOWLIST),
        "skills": {
            name: dict(manifest)
            for name, manifest in sorted(source_manifests.items())
        },
    }


def sync_runtime_skills(
    source_root: str | os.PathLike[str],
    deployed_public_root: str | os.PathLike[str],
    *,
    required_skills: Sequence[str] = DEFAULT_REQUIRED_SKILLS,
    lock_timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Authoritatively install and verify every source-managed skill bundle."""

    source_path = Path(source_root).expanduser().resolve()
    deployed_path = Path(deployed_public_root).expanduser().resolve(strict=False)
    skills_parent = deployed_path.parent
    if not skills_parent.is_dir() or skills_parent.is_symlink():
        raise SkillSyncError(f"deployed skills parent is missing or unsafe: {skills_parent}")

    required = {_validate_skill_name(name) for name in required_skills}
    lock_path = skills_parent / LOCK_FILENAME
    with _exclusive_lock(lock_path, lock_timeout_seconds):
        source_manifests = _discover_source_manifests(source_path)
        missing = sorted(required.difference(source_manifests))
        if missing:
            raise SkillSyncError(
                "required runtime skill source bundle(s) missing: " + ", ".join(missing)
            )

        expected_state = _state_payload(source_manifests)
        state_path = deployed_path / STATE_FILENAME
        current_state = _load_state(state_path) if deployed_path.exists() else None
        previous_managed = set(
            current_state.get("managed_skills", []) if current_state else source_manifests
        )
        current_names = set(source_manifests)
        pruned_skills = sorted(previous_managed.difference(current_names))

        deployed_hash: str | None = None
        try:
            deployed = _deployed_manifests(deployed_path, current_names)
            deployed_hash = _bundle_manifest_hash(deployed)
        except SkillSyncError:
            deployed = {}

        if (
            current_state == expected_state
            and not pruned_skills
            and deployed_hash == expected_state["bundle_manifest_hash"]
            and all(
                deployed[name]["manifest_hash"]
                == source_manifests[name]["manifest_hash"]
                for name in current_names
            )
        ):
            return _result_payload(
                outcome="verified",
                deployed_public_root=deployed_path,
                source_manifests=source_manifests,
                deployed_manifest_hash=deployed_hash,
            )

        stage_path = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=skills_parent))
        live_swapped = False
        try:
            _copy_unmanaged_public_skills(
                deployed_path,
                stage_path,
                previous_managed.union(current_names),
            )
            for name in sorted(source_manifests):
                _copy_source_bundle(
                    source_path,
                    stage_path,
                    source_manifests[name],
                )

            staged_manifests = _deployed_manifests(stage_path, current_names)
            for name in current_names:
                if staged_manifests[name] != source_manifests[name]:
                    raise SkillSyncError(
                        f"staged runtime skill bundle failed verification: {name}"
                    )
            staged_hash = _bundle_manifest_hash(staged_manifests)
            if staged_hash != expected_state["bundle_manifest_hash"]:
                raise SkillSyncError("staged runtime skill set hash does not match source")
            _write_json(stage_path / STATE_FILENAME, expected_state)

            if deployed_path.exists():
                _atomic_exchange(stage_path, deployed_path)
                live_swapped = True
            else:
                os.replace(stage_path, deployed_path)
            _fsync_directory(skills_parent)

            installed_state = _load_state(deployed_path / STATE_FILENAME)
            installed_manifests = _deployed_manifests(deployed_path, current_names)
            installed_hash = _bundle_manifest_hash(installed_manifests)
            if installed_state != expected_state or installed_hash != staged_hash:
                if live_swapped and stage_path.exists():
                    _atomic_exchange(stage_path, deployed_path)
                    _fsync_directory(skills_parent)
                    live_swapped = False
                raise SkillSyncError(
                    "installed runtime skill set failed post-promotion verification"
                )

            cleanup_warning: str | None = None
            if live_swapped and stage_path.exists():
                try:
                    shutil.rmtree(stage_path)
                except OSError as exc:
                    cleanup_warning = str(exc)
            result = _result_payload(
                outcome="updated",
                deployed_public_root=deployed_path,
                source_manifests=source_manifests,
                deployed_manifest_hash=installed_hash,
                pruned_skills=pruned_skills,
            )
            if cleanup_warning:
                result["cleanup_warning"] = cleanup_warning
            return result
        except SkillSyncError:
            raise
        except Exception as exc:
            raise SkillSyncError(f"runtime skill staging/deployment failed: {exc}") from exc
        finally:
            if stage_path.exists() and not live_swapped:
                shutil.rmtree(stage_path, ignore_errors=True)


def verify_runtime_sync_payload(
    payload: Mapping[str, Any],
    deployed_public_root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Re-hash the live bundle at child startup and bind it to parent telemetry."""

    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise SkillSyncError("runtime skill sync telemetry schema is invalid")
    deployed_path = Path(deployed_public_root).expanduser().resolve(strict=False)
    recorded_path = payload.get("deployed_path")
    if not isinstance(recorded_path, str) or Path(recorded_path).resolve(strict=False) != deployed_path:
        raise SkillSyncError("runtime skill sync telemetry points to a different deployment")
    names = payload.get("managed_skills")
    expected_skills = payload.get("skills")
    if (
        not isinstance(names, list)
        or not isinstance(expected_skills, Mapping)
        or sorted(names) != sorted(expected_skills)
    ):
        raise SkillSyncError("runtime skill sync telemetry skill inventory is invalid")
    for name in names:
        _validate_skill_name(name)

    actual_manifests = _deployed_manifests(deployed_path, names)
    for name in names:
        if actual_manifests[name] != expected_skills[name]:
            raise SkillSyncError(f"runtime skill bundle changed before execution: {name}")
    actual_hash = _bundle_manifest_hash(actual_manifests)
    source_hash = payload.get("source_manifest_hash")
    expected_deployed_hash = payload.get("deployed_manifest_hash")
    if actual_hash != source_hash or actual_hash != expected_deployed_hash:
        raise SkillSyncError("runtime skill set hash changed before execution")

    state = _load_state(deployed_path / STATE_FILENAME)
    if state is None or state.get("bundle_manifest_hash") != actual_hash:
        raise SkillSyncError("persisted runtime skill manifest does not match execution bytes")
    verified = dict(payload)
    verified["deployed_manifest_hash"] = actual_hash
    verified["runtime_verified"] = True
    return verified


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--deployed-public-root", required=True)
    parser.add_argument(
        "--required-skill",
        action="append",
        dest="required_skills",
        help="Required source bundle name; repeat for multiple skills.",
    )
    parser.add_argument("--lock-timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    required = (
        tuple(args.required_skills)
        if args.required_skills is not None
        else DEFAULT_REQUIRED_SKILLS
    )
    try:
        result = sync_runtime_skills(
            args.source_root,
            args.deployed_public_root,
            required_skills=required,
            lock_timeout_seconds=args.lock_timeout,
        )
    except Exception as exc:  # CLI boundary: always emit a machine-readable failure.
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "outcome": "failed",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
