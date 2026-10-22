"""Reproduce this study's static checks without importing application modules."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone


def inventory_errors(tree: dict[str, str], rows: list[dict]) -> list[str]:
    """Reject omissions, additions and duplicate rows against the pinned tree."""
    expected = {path for path in tree if path.endswith(".py")}
    listed = {row["path"] for row in rows}
    errors = []
    if len(rows) != len(listed):
        errors.append("Duplicate Python inventory paths")
    errors.extend(f"Missing Python inventory path: {path}" for path in sorted(expected - listed))
    errors.extend(f"Unexpected Python inventory path: {path}" for path in sorted(listed - expected))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror", type=Path)
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    repo = output.parents[2]
    contract = json.loads((output / "study-contract.json").read_text())
    mirror = args.mirror or Path(contract["mirror"])
    commit = contract["source_commit"]
    inventory = json.loads((output / "python-inventory.json").read_text())
    indexed = {row["path"]: row for row in inventory}
    now = datetime.now(timezone.utc).isoformat()
    source_errors: list[str] = []
    tree = {}
    result = subprocess.run(
        ["git", "ls-tree", "-r", commit], cwd=repo, capture_output=True, text=True, check=True
    )
    for line in result.stdout.splitlines():
        metadata, path = line.split("\t", 1)
        tree[path] = metadata.split()[2]
    source_errors.extend(inventory_errors(tree, inventory))
    tracked_python_count = sum(path.endswith(".py") for path in tree)
    for row in inventory:
        path = mirror / row["path"]
        if not path.is_file():
            source_errors.append(f"Missing frozen source: {row['path']}")
            continue
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != tree.get(row["path"]):
            source_errors.append(f"Git blob mismatch: {row['path']}")
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            source_errors.append(f"SHA-256 mismatch: {row['path']}")
        if len(data.splitlines()) != row["lines"]:
            source_errors.append(f"Line-count mismatch: {row['path']}")
        try:
            ast.parse(data, filename=row["path"])
        except (SyntaxError, ValueError) as exc:
            source_errors.append(f"AST error: {row['path']}: {exc}")

    coverage_errors: list[str] = []
    owners = []
    supplemental = 0
    for owner in sorted({row["owner"] for row in inventory if row["category"] == "application"}):
        required = {path: row for path, row in indexed.items() if row["owner"] == owner}
        rows = json.loads((output / "areas" / f"{owner}-coverage.json").read_text())
        seen = {}
        for row in rows:
            path = mirror / row["path"]
            if not path.is_file():
                coverage_errors.append(f"Missing receipt source: {row['path']}")
                continue
            data = path.read_bytes()
            length = len(data.splitlines())
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                coverage_errors.append(f"Receipt hash mismatch: {row['path']}")
            spans: list[list[int]] = []
            for start, end in sorted(row.get("read_ranges", [])):
                if not 1 <= start <= end <= length:
                    coverage_errors.append(f"Receipt range invalid: {row['path']}:{start}-{end}")
                if spans and start <= spans[-1][1] + 1:
                    spans[-1][1] = max(spans[-1][1], end)
                else:
                    spans.append([start, end])
            full = spans == [[1, length]]
            if row["depth"] == "full" and not full:
                coverage_errors.append(f"Unsupported full-read claim: {row['path']}")
            if row["path"] in required:
                if row["path"] in seen:
                    coverage_errors.append(f"Duplicate primary receipt: {row['path']}")
                seen[row["path"]] = full
            else:
                supplemental += 1
        for path in required.keys() - seen.keys():
            coverage_errors.append(f"Missing primary receipt: {path}")
        full_count = sum(seen.values())
        if owner != "coordinator" and full_count != len(required):
            coverage_errors.append(f"Incomplete specialist owner: {owner}")
        owners.append({"owner": owner, "files": len(required),
                       "lines": sum(row["lines"] for row in required.values()),
                       "full_files": full_count, "partial_files": len(required) - full_count})

    document_errors: list[str] = []
    anchors = set()
    link_count = 0
    mermaid_count = 0
    source_pattern = re.compile(
        r"((?:backend|deerflow_bridge|drf2|datamcps|scripts|docs|frontend|\.github)/"
        r"[A-Za-z0-9_./-]+\.(?:py|vue|js|ts|md|sh|json|ya?ml|toml)):(\d+)(?:[-–](\d+))?"
    )
    markdown_files = list(output.rglob("*.md"))
    own_prefix = str(output.relative_to(repo)) + "/"
    delta_manifest = output / "main-advance-inventory.json"
    delta_mirror = None
    if delta_manifest.exists():
        delta_mirror = Path(json.loads(delta_manifest.read_text())["mirror"])
    for document in markdown_files:
        text = document.read_text()
        document_mirror = delta_mirror if document.name == "main-advance.md" else mirror
        if text.count("```") % 2:
            document_errors.append(f"Unbalanced code fences: {document.name}")
        mermaid_count += text.count("```mermaid")
        for match in source_pattern.finditer(text):
            path, start = match[1], int(match[2])
            end = int(match[3] or match[2])
            if path.startswith(own_prefix):
                continue  # Review history may cite newly authored study documents.
            anchor_mirror = document_mirror
            prefix = text[max(0, match.start() - 120):match.start()]
            if delta_mirror is not None and prefix.endswith(str(delta_mirror) + "/"):
                anchor_mirror = delta_mirror
            source = anchor_mirror / path
            if not source.is_file():
                document_errors.append(f"Unavailable cited source: {path}")
            elif not 1 <= start <= end <= len(source.read_bytes().splitlines()):
                document_errors.append(f"Source anchor out of bounds: {path}:{start}-{end}")
            anchors.add((path, start, end))
        for match in re.finditer(r"\]\(([^)]+)\)", text):
            target = match[1].strip("<>")
            link_count += 1
            if target.startswith(("http:", "https:", "app:", "codex:", "#", "mailto:")):
                continue
            target = target.split("#", 1)[0]
            target = re.sub(r":\d+$", "", target)
            if target:
                path = Path(target) if target.startswith("/") else document.parent / target
                if not path.exists():
                    document_errors.append(f"Missing link: {document.name}: {target}")

    def save(name: str, payload: dict) -> None:
        (output / name).write_text(json.dumps(payload, indent=2) + "\n")

    common = {"source_commit": commit, "checked_utc": now}
    save("source-validation.json", {**common, "tracked_python_files": tracked_python_count,
         "lines": sum(row["lines"] for row in inventory), "errors": source_errors,
         "application_imports": False, "application_execution": False,
         "status": "passed" if not source_errors else "failed"})
    save("coverage-validation.json", {**common,
         "application_files": sum(row["category"] == "application" for row in inventory),
         "application_lines": sum(row["lines"] for row in inventory if row["category"] == "application"),
         "assigned_specialist_files": sum(row["files"] for row in owners if row["owner"] != "coordinator"),
         "specialist_full_files": sum(row["full_files"] for row in owners if row["owner"] != "coordinator"),
         "fresh_full_primary_files": sum(row["full_files"] for row in owners),
         "coordinator_note": "Fresh partial ranges and exact-hash historical reads remain separately labeled.",
         "tests_indexed": sum(row["category"] == "tests" for row in inventory),
         "vendor_non_test_indexed": sum(row["category"] == "vendor" for row in inventory),
         "supplemental_receipt_entries": supplemental, "owners": owners,
         "errors": coverage_errors, "status": "passed" if not coverage_errors else "failed"})
    save("document-validation.json", {**common, "markdown_files": len(markdown_files),
         "distinct_source_anchors": len(anchors), "markdown_links_checked": link_count,
         "mermaid_blocks": mermaid_count, "errors": document_errors,
         "status": "passed" if not document_errors else "failed",
         "mermaid": "Source claims and code fences checked; no raster-rendering proof claimed."})
    errors = source_errors + coverage_errors + document_errors
    specialist_count = sum(row["files"] for row in owners if row["owner"] != "coordinator")
    print(json.dumps({"source_files": tracked_python_count, "specialist_files": specialist_count,
                      "source_anchors": len(anchors), "links": link_count,
                      "mermaid_blocks": mermaid_count, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
