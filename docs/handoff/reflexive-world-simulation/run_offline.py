#!/usr/bin/env python3
"""Freeze source outside the managed .codex path, then use the unchanged guard.

This is a copy/receipt wrapper, not an alternative test runner or isolation layer.
It imports no application code. All application execution is inside the existing
main_offline_pytest.py audit boundary. It never copies saved data or credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True, type=Path)
    parser.add_argument('--label', default='world')
    args, pytest_args = parser.parse_known_args()
    root = Path(__file__).resolve().parents[3]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run = Path(tempfile.mkdtemp(prefix=f'drf-{args.label}-{stamp}-')).resolve()
    source = run / 'source'
    source.mkdir()
    suffixes = {'.py', '.json', '.toml', '.yaml', '.yml', '.md', '.txt', '.csv', '.jinja2'}
    excluded = {'__pycache__', '.pytest_cache', '.git', '.venv', 'node_modules', 'uploads', 'logs', '.env', 'cache'}
    manifest = {}
    roots = ['backend/app', 'backend/tests', 'backend/scripts', 'deerflow_bridge']
    candidates = [root / 'backend/pyproject.toml',
                  root / 'docs/handoff/reflexive-world-simulation/run_live_evaluation.py',
                  root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/live-policy.json',
                  root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/public-grammar/live-policy.json',
                  root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/public-grammar/preflight.json',
                  root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/live-policy.json',
                  root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/preflight.json',
                  root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/server-bound-review/live-policy.json']
    for folder in roots:
        candidates.extend((root / folder).rglob('*'))
    for path in sorted(set(candidates)):
        relative = path.relative_to(root)
        if set(relative.parts) & excluded or any(p.startswith('.env') for p in relative.parts):
            continue
        if path.is_symlink():
            continue
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
            raise ValueError(f'Symlink source parent: {relative}')
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError(f'Oversized source: {relative}')
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        manifest[str(relative)] = sha(target)
        if manifest[str(relative)] != sha(path):
            raise ValueError(f'Source changed while freezing: {relative}')
    (run / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    command = [str(args.python), '-I', '-S', '-B', 'backend/scripts/main_offline_pytest.py',
               '--evidence-dir', str(run / 'evidence'), *pytest_args]
    with (run / 'console.log').open('w') as output:
        completed = subprocess.run(command, cwd=source, stdout=output, stderr=subprocess.STDOUT, check=False)
    drift = [name for name, value in manifest.items()
             if not (root / name).is_file() or sha(root / name) != value or sha(source / name) != value]
    summary = {'exitCode': completed.returncode, 'sourceDrift': drift, 'files': len(manifest),
               'command': command, 'source': str(source), 'evidence': str(run / 'evidence')}
    (run / 'verification-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print((run / 'console.log').read_text()[-16000:])
    print(json.dumps(summary))
    return completed.returncode if not drift else 2


if __name__ == '__main__':
    sys.exit(main())
