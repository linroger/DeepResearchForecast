"""Immutable input and derived-result bindings for the world engine."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
from contextlib import contextmanager

from .contracts import ENGINE, WorldError, anchor_enabled, canonical_json, clone, digest, require, validate_preparation_pin, validate_spec
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


def _read_anchor_preparation(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0))
    except OSError:
        raise WorldError('anchor_binding_mismatch', 'Anchor preparation is missing or indirect') from None
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= 16 * 1024 * 1024,
                'anchor_binding_mismatch', 'Invalid anchor preparation file')
        chunks, remaining = [], 16 * 1024 * 1024 + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
        require(len(raw) == info.st_size, 'anchor_binding_mismatch', 'Anchor preparation changed during read')
        return raw
    except OSError:
        raise WorldError('anchor_binding_mismatch', 'Anchor preparation could not be read safely') from None
    finally:
        os.close(fd)


def _write_anchor_preparation(path, raw):
    fd, temporary = tempfile.mkstemp(prefix='.anchor-preparation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def input_manifest(spec: dict) -> dict:
    result = {'schemaVersion': 'world-input-manifest/v1', 'engine': ENGINE,
            'simulationId': spec['simulationId'], 'generationId': spec['generationId'],
            'specHash': digest(spec),
            'specSha256': hashlib.sha256((canonical_json(spec) + '\n').encode('utf-8')).hexdigest(),
            'sourceBindings': spec['sourceBindings']}
    if anchor_enabled(spec):
        result['worldAnchor'] = clone(spec['sourceBindings']['worldAnchor']['pin'])
        result['worldAnchorPreparation'] = {'path': 'world_anchor_preparation.json',
            'sha256': spec['sourceBindings']['worldAnchor']['preparationSha256']}
    return result


def validate_preparation_binding(bundle, *, expected_sources=None, research_generation_id=None):
    """Validate the shared source authority without resealing or alias fallback."""
    from ..research_preparation import validate_preparation_context
    try:
        validate_preparation_context(bundle, expected_sources=expected_sources)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise WorldError('invalid_preparation_context', 'Research preparation proof or source binding is invalid') from None
    if research_generation_id is not None:
        binding = bundle['source'].get('source_binding')
        require(isinstance(binding, dict) and binding.get('research_generation_id') == research_generation_id,
                'preparation_generation_mismatch', 'Research preparation belongs to another input generation')
    return clone(bundle)


def load_preparation(directory: Path, spec: dict):
    """A present native pin makes both shared preparation artifacts mandatory."""
    validate_preparation_pin(spec)
    bindings = spec['sourceBindings']
    if 'preparationContext' not in bindings:
        return None
    pin = bindings['preparationContext']
    require(isinstance(pin, dict) and set(pin) == {'schemaVersion', 'contentSha256', 'source'}
            and pin['schemaVersion'] == 'research-preparation/v1',
            'invalid_preparation_context', 'Invalid native research preparation pin')
    from ..research_preparation import load_preparation_context
    try:
        bundle = load_preparation_context(directory, expected_sha256=pin['contentSha256'],
                                          expected_sources=pin['source'])
    except (ValueError, TypeError, KeyError, OSError):
        raise WorldError('invalid_preparation_context', 'Pinned research preparation is missing or changed') from None
    return validate_preparation_binding(bundle, research_generation_id=bindings.get('researchGenerationId'))


def seal_inputs(directory: Path, spec: dict, *, preparation_context=None, anchor_context=None) -> dict:
    directory = Path(directory)
    spec = validate_spec(spec)
    validate_mechanisms(spec)
    pin = spec['sourceBindings'].get('preparationContext')
    require((pin is not None) == (preparation_context is not None),
            'invalid_preparation_context', 'Native preparation must carry its exact pinned bundle')
    if preparation_context is not None:
        preparation_context = validate_preparation_binding(preparation_context,
            expected_sources=pin['source'], research_generation_id=spec['sourceBindings']['researchGenerationId'])
        require(preparation_context['content_sha256'] == pin['contentSha256'],
                'invalid_preparation_context', 'Native preparation bundle fingerprint differs from its pin')
    if anchor_enabled(spec) or anchor_context is not None:
        from .compiler import anchor_preparation_bytes, validate_world_anchor
        validate_world_anchor(spec, anchor_context)
        preparation = anchor_preparation_bytes(spec)
    else:
        preparation = None
    path = directory / 'world_spec.json'
    manifest_path = directory / 'world_input_manifest.json'
    with exclusive_file(directory / 'world_prepare.lock'):
        require(not path.exists() and not manifest_path.exists() and not (directory / 'world.sqlite3').exists(),
                'generation_exists', 'Prepared world generations are immutable; create a new simulation to replace one')
        if preparation_context is not None:
            from ..research_preparation import BUNDLE_FILE, MANIFEST_FILE, write_preparation_context
            if (directory / BUNDLE_FILE).exists() or (directory / MANIFEST_FILE).exists():
                load_preparation(directory, spec)  # Never replace an existing generation or repair partial proof.
            else:
                write_preparation_context(directory, preparation_context)
        if preparation is not None:
            require(not (directory / 'world_anchor_preparation.json').exists(),
                    'generation_exists', 'Anchor preparation is immutable')
            _write_anchor_preparation(directory / 'world_anchor_preparation.json', preparation)
        atomic_json(path, spec)
        manifest = input_manifest(spec)
        atomic_json(manifest_path, manifest)
    return manifest


def load_inputs(directory: Path, *, simulation_id: str | None = None,
                expected_manifest_sha256: str | None = None, anchor_context=None) -> tuple[dict, dict]:
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
    load_preparation(directory, spec)
    if anchor_enabled(spec):
        from .compiler import restore_anchor_preparation
        require(manifest.get('worldAnchor') == spec['sourceBindings']['worldAnchor']['pin'],
                'anchor_binding_mismatch', 'Prepared world anchor pin changed')
        if anchor_context is None:
            from ..world_anchor import load_runtime_anchor
            anchor_context = load_runtime_anchor({'simulation_id': spec['simulationId'],
                                                  'world_anchor': manifest['worldAnchor']}, directory)
        entry = manifest.get('worldAnchorPreparation')
        require(isinstance(entry, dict) and set(entry) == {'path', 'sha256'}
                and entry['path'] == 'world_anchor_preparation.json'
                and entry['sha256'] == spec['sourceBindings']['worldAnchor']['preparationSha256'],
                'anchor_binding_mismatch', 'Prepared world candidate binding is missing')
        preparation = _read_anchor_preparation(directory / entry['path'])
        require(hashlib.sha256(preparation).hexdigest() == entry['sha256'],
                'anchor_binding_mismatch', 'Prepared world candidate bytes changed')
        spec = restore_anchor_preparation(spec, preparation, anchor_context)
    else:
        require('worldAnchor' not in manifest and 'worldAnchorPreparation' not in manifest and anchor_context is None,
                'anchor_binding_mismatch', 'An unpinned world cannot acquire anchor mode during reuse')
    return spec, manifest
