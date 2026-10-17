"""Immutable input and derived-result bindings for the world engine."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager

from .contracts import ENGINE, canonical_json, digest, require, validate_spec
from .kernel import validate_mechanisms


@contextmanager
def exclusive_file(path: Path, *, blocking=True):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'indirect_artifact', 'World lock cannot be a symbolic link')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield fd
    finally:
        os.close(fd)


def atomic_json(path: Path, value: dict, *, preserve_unicode=False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            encoded = canonical_json(value)  # validate closed JSON even for exact source strings
            if preserve_unicode:
                encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            stream.write(encoded + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path) -> dict:
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'missing_artifact', 'Required world artifact is missing or indirect')
    require(path.stat().st_size <= 16 * 1024 * 1024, 'artifact_too_large', 'World artifact exceeds its read bound')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'invalid_json', 'Duplicate artifact key')
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)
    canonical_json(value)
    require(isinstance(value, dict), 'invalid_artifact', 'World artifact must be an object')
    return value


def file_digest(path: Path) -> str:
    require(not path.is_symlink(), 'indirect_artifact', 'World artifacts cannot be symbolic links')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_manifest(spec: dict) -> dict:
    return {'schemaVersion': 'world-input-manifest/v1', 'engine': ENGINE,
            'simulationId': spec['simulationId'], 'generationId': spec['generationId'],
            'specHash': digest(spec),
            'specSha256': hashlib.sha256((canonical_json(spec) + '\n').encode('utf-8')).hexdigest(),
            'sourceBindings': spec['sourceBindings']}


def seal_inputs(directory: Path, spec: dict) -> dict:
    directory = Path(directory)
    spec = validate_spec(spec)
    validate_mechanisms(spec)
    path = directory / 'world_spec.json'
    manifest_path = directory / 'world_input_manifest.json'
    with exclusive_file(directory / 'world_prepare.lock'):
        require(not path.exists() and not manifest_path.exists() and not (directory / 'world.sqlite3').exists(),
                'generation_exists', 'Prepared world generations are immutable; create a new simulation to replace one')
        atomic_json(path, spec)
        manifest = input_manifest(spec)
        atomic_json(manifest_path, manifest)
    return manifest


def load_inputs(directory: Path, *, simulation_id: str | None = None,
                expected_manifest_sha256: str | None = None) -> tuple[dict, dict]:
    directory = Path(directory)
    path = directory / 'world_spec.json'
    manifest_path = directory / 'world_input_manifest.json'
    manifest = read_json(manifest_path)
    require(manifest.get('schemaVersion') == 'world-input-manifest/v1' and manifest.get('engine') == ENGINE,
            'unsupported_engine', 'Unknown world input manifest')
    require(expected_manifest_sha256 is None or file_digest(manifest_path) == expected_manifest_sha256,
            'input_binding_mismatch', 'Prepared world manifest changed')
    require(file_digest(path) == manifest.get('specSha256'), 'input_binding_mismatch', 'Prepared world bytes changed')
    spec = validate_spec(read_json(path))
    validate_mechanisms(spec)
    require(digest(spec) == manifest.get('specHash') and spec['simulationId'] == manifest.get('simulationId')
            and spec['generationId'] == manifest.get('generationId')
            and spec['sourceBindings'] == manifest.get('sourceBindings')
            and (simulation_id is None or simulation_id == spec['simulationId']),
            'input_binding_mismatch', 'World inputs do not match their prepared generation')
    return spec, manifest
