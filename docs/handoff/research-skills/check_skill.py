#!/usr/bin/env python3
"""Self-check for a research method skill against docs/handoff/research-skills/design.md §3–4.

Usage (from the repo root):
  backend/.venv/bin/python docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/<name>
  backend/.venv/bin/python docs/handoff/research-skills/check_skill.py --sectors deerflow_bridge/skills/industry-research/references/sectors-technology.md
Prints every violation; exit 0 when clean.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve()
for parent in ROOT.parents:
    if (parent / "deerflow_bridge" / "data_catalog.py").is_file():
        ROOT = parent
        break
else:
    raise SystemExit("run this checker from inside the DeepResearchForecast checkout")
sys.path.insert(0, str(ROOT / "deerflow_bridge"))
import data_catalog  # noqa: E402

HEADINGS = ["Activation", "Plan", "Investigate", "Synthesize", "Gaps", "References"]
CAPS = {"Activation": 900, "Plan": 1800, "Investigate": 2400, "Synthesize": 1500, "Gaps": 700}
INJECTED = ("Plan", "Investigate", "Synthesize", "Gaps")
SECTOR_KEYS = {
    "sectors-technology.md": ["semiconductors", "ai-compute-datacenters", "cloud-software", "telecom-networks",
                              "internet-platforms-media", "autos-ev", "energy-storage-batteries", "frontier-tech",
                              "aerospace-defense"],
    "sectors-economy.md": ["power-utilities", "renewables", "oil-gas", "mining-metals", "agriculture-food",
                           "biopharma", "healthcare-services-medtech", "banking-insurance",
                           "real-estate-construction", "consumer-retail", "industrials-machinery",
                           "transport-logistics"],
}
SECTOR_LABELS = ["Unit and segments", "Decisive metrics", "Supply and capacity", "Cycle and price signals",
                 "Forecast drivers", "Sources", "Traps"]
ID_RE = re.compile(r"(?<![A-Za-z0-9_])((?:fred|bls|bis|imf|wb|usgov):[A-Za-z0-9_./#%-]+[A-Za-z0-9_])")


def catalog_errors(text: str, where: str) -> list[str]:
    errors = []
    for match in ID_RE.finditer(text):
        identity = match.group(1)
        base = identity.split("#", 1)[0]
        if data_catalog.lookup(base) is None:
            errors.append(f"{where}: catalog ID not in data_catalog: {identity}")
    return errors


def sections(body: str) -> dict[str, str]:
    found: dict[str, str] = {}
    parts = re.split(r"(?m)^## (.+?)\s*$", body)
    for heading, text in zip(parts[1::2], parts[2::2]):
        found[heading.strip()] = text.strip("\n")
    return found


def check_skill(folder: Path) -> list[str]:
    errors: list[str] = []
    skill = folder / "SKILL.md"
    if not skill.is_file():
        return [f"{skill}: missing"]
    text = skill.read_text(encoding="utf-8")
    if len(text) > 11000:
        errors.append(f"SKILL.md is {len(text)} chars (cap 11000)")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        return errors + ["frontmatter missing or malformed"]
    front = match.group(1)
    keys = re.findall(r"(?m)^([A-Za-z_-]+):", front)
    if sorted(keys) != ["description", "name"]:
        errors.append(f"frontmatter keys must be exactly name, description (found {keys})")
    name = re.search(r"(?m)^name:\s*(\S+)\s*$", front)
    if not name or name.group(1) != folder.name:
        errors.append(f"frontmatter name must equal folder name {folder.name!r}")
    desc = re.search(r"(?ms)^description:\s*(.+?)(?=^\w[\w-]*:|\Z)", front)
    desc_text = re.sub(r"\s+", " ", desc.group(1)).strip().strip(">-").strip() if desc else ""
    if not desc_text:
        errors.append("description missing")
    elif len(desc_text) > 1000:
        errors.append(f"description is {len(desc_text)} chars (cap 1000)")
    if "<" in desc_text or ">" in desc_text.lstrip(">"):
        errors.append("description contains '<' or '>'")
    body = text[match.end():]
    if not re.match(r"\s*# \S", body):
        errors.append("body must start with a '# Title' line")
    found = sections(body)
    order = [h for h in re.findall(r"(?m)^## (.+?)\s*$", body)]
    if order != HEADINGS:
        errors.append(f"## headings must be exactly {HEADINGS} in order (found {order})")
    for heading, cap in CAPS.items():
        size = len(found.get(heading, ""))
        if size == 0:
            errors.append(f"## {heading} is empty")
        elif size > cap:
            errors.append(f"## {heading} is {size} chars (cap {cap})")
    for heading in INJECTED:
        part = found.get(heading, "")
        if "$" in part:
            errors.append(f"## {heading} contains '$' (write USD)")
        if re.search(r"\[S\d+\]", part):
            errors.append(f"## {heading} contains a numbered [S<n>] marker")
    if re.search(r"deep-research\s*§", text):
        errors.append("contains a 'deep-research §N' reference")
    errors += catalog_errors(text, "SKILL.md")
    for link in re.findall(r"\]\((references/[^)#]+)\)", text):
        if not (folder / link).is_file():
            errors.append(f"broken reference link: {link}")
    for ref in sorted((folder / "references").glob("*.md")) if (folder / "references").is_dir() else []:
        ref_text = ref.read_text(encoding="utf-8")
        if len(ref_text) > 14000:
            errors.append(f"{ref.name} is {len(ref_text)} chars (cap 14000)")
        errors += catalog_errors(ref_text, ref.name)
        if ref.name not in SECTOR_KEYS and f"references/{ref.name}" not in text:
            errors.append(f"{ref.name} is not linked from ## References")
    return errors


def check_sectors(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if len(text) > 14000:
        errors.append(f"{path.name} is {len(text)} chars (cap 14000)")
    blocks = dict(zip(re.findall(r"(?m)^### (\S+)\s*$", text), re.split(r"(?m)^### \S+\s*$", text)[1:]))
    expected = SECTOR_KEYS.get(path.name, [])
    if list(blocks) != expected:
        errors.append(f"### sector keys must be exactly {expected} in order (found {list(blocks)})")
    for key, block in blocks.items():
        block = block.strip("\n")
        if len(block) > 1200:
            errors.append(f"### {key} is {len(block)} chars (cap 1200)")
        for label in SECTOR_LABELS:
            if f"**{label}**" not in block:
                errors.append(f"### {key} lacks **{label}**")
        if "$" in block:
            errors.append(f"### {key} contains '$' (write USD)")
    errors += catalog_errors(text, path.name)
    return errors


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--sectors"]:
        problems = check_sectors(Path(args[1]))
    else:
        problems = check_skill(Path(args[0]))
    for problem in problems:
        print("FAIL", problem)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
