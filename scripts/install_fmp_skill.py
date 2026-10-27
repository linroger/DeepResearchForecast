#!/usr/bin/env python3
"""Install a self-contained Codex skill from reviewed project source; no providers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


REPO = Path(__file__).resolve().parents[1]
NAME = "fmp-research"


def install(repo: Path, skills_root: Path) -> dict:
    source = repo / "deerflow_bridge" / "skills" / NAME
    client = repo / "deerflow_bridge" / "fmp_mcp.py"
    if not source.is_dir() or not client.is_file() or client.is_symlink():
        raise ValueError("complete canonical skill and client are required")
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("skill symlinks are not supported")
    files = [path for path in files if "__pycache__" not in path.parts and path.suffix != ".pyc"]
    skills_root.mkdir(parents=True, exist_ok=True)
    destination = skills_root / NAME
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("skill already exists; review the existing installation before replacing it")
    staging = Path(tempfile.mkdtemp(prefix=".fmp-skill-", dir=skills_root))
    try:
        hashes = {}
        for path in files:
            relative = path.relative_to(source)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            hashes[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
        target = staging / "scripts" / "fmp_mcp.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(client, target)
        hashes["scripts/fmp_mcp.py"] = hashlib.sha256(target.read_bytes()).hexdigest()
        receipt = {"schema": "fmp-skill-install/v1", "name": NAME,
                   "files": hashes, "canonical_client": "deerflow_bridge/fmp_mcp.py"}
        (staging / "installation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        os.rename(staging, destination)
        return {"installed": str(destination), **receipt}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills")
    args = parser.parse_args()
    print(json.dumps(install(REPO, args.skills_root.expanduser().resolve()), indent=2))


if __name__ == "__main__":
    main()
