#!/usr/bin/env python3
"""Freeze trusted repository source for the existing offline runner.

Managed worktrees live below .codex, which the runner intentionally refuses to
read. Copy tracked and nonignored owned source into a fresh private /tmp folder;
never copy credentials, saved runtime data, dependencies, or follow symlinks.
This prepares inputs only. It does not execute tests or weaken the runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".env", ".venv", "node_modules", "__pycache__",
                  ".pytest_cache", ".ruff_cache", ".codex", ".claude"}
EXCLUDED_ROOTS = {"backend/uploads", "backend/logs", "backend/data", "logs", "log", "tmp"}


def prepare(label: str) -> dict:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
    ).decode().split("\0")
    mirror = Path(tempfile.mkdtemp(prefix=f"drf-oddsense-{label}-", dir="/tmp")).resolve()
    entries, skipped = [], []
    for relative in sorted(set(filter(None, paths))):
        path = Path(relative)
        if (path.is_absolute() or ".." in path.parts
                or any(part in EXCLUDED_PARTS for part in path.parts)
                or any(part.startswith(".env.") and part != ".env.example" for part in path.parts)
                or any(relative == stem or relative.startswith(stem + "/") for stem in EXCLUDED_ROOTS)):
            skipped.append({"path": relative, "reason": "excluded"})
            continue
        source = ROOT / path
        try:
            info = source.lstat()
        except FileNotFoundError:
            skipped.append({"path": relative, "reason": "absent"})
            continue
        if not stat.S_ISREG(info.st_mode) or source.resolve().parent != source.parent.resolve():
            skipped.append({"path": relative, "reason": "nonregular"})
            continue
        if any((ROOT / Path(*path.parts[:index])).is_symlink()
               for index in range(1, len(path.parts))):
            skipped.append({"path": relative, "reason": "symlink_parent"})
            continue
        raw = source.read_bytes()
        destination = mirror / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        os.chmod(destination, stat.S_IMODE(info.st_mode))
        entries.append({"path": relative, "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest()})
    receipt = {"schema_version": 1, "source_root": str(ROOT), "mirror": str(mirror),
               "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
               "files": entries, "skipped": skipped}
    (mirror / "oddsense-source-manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return {"mirror": str(mirror), "files": len(entries), "skipped": len(skipped)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="verify")
    args = parser.parse_args()
    if not args.label.replace("-", "").isalnum() or len(args.label) > 48:
        parser.error("label must be 1-48 letters, digits or hyphens")
    print(json.dumps(prepare(args.label)))
