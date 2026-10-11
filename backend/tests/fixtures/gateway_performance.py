"""Bounded, offline gateway regex timing workloads for an isolated interpreter."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "deerflow_bridge"))

import research_gateway as rg  # noqa: E402


def _r3_timing_probe(case: str) -> dict:
    """Best-of-3 seconds for the C1 timing cases; run in a fresh interpreter by
    :func:`_r3_isolated` (a super-linear regex holds the GIL, so an in-process
    check would hang the suite instead of failing it)."""
    def best(fn) -> float:
        times = []
        for _ in range(3):
            started = time.perf_counter()
            fn()
            times.append(time.perf_counter() - started)
        return min(times)

    out: dict = {}
    if case == "whitespace":
        for name, unit in (("space", " "), ("nbsp", "\u00a0"), ("tab", "\t"), ("ideographic", "\u3000"),
                           ("mixed", " \t\u00a0")):
            line = "Capacity 176 GW." + unit * (12_000 // len(unit)) + "Queues 40 months."
            assert rg.neutralize_instructions(line) == line
            out[name] = best(lambda line=line: rg.neutralize_instructions(line))
    elif case == "tools":
        import tempfile

        root = Path(tempfile.mkdtemp())
        head = "# Grid queues\n\nCapacity reached 176 GW." + " " * 2_500 + "Queues grew."
        page = head + "x" * max(0, 2_600 - len(head))
        snippet = "Capacity 176 GW." + "\u00a0" * 2_500 + "Queues grew."
        payload = json.dumps({"results": [{"title": "Grid", "url": "https://grid.org/a", "content": snippet}]})
        runs: dict = {"fetch": [], "search": []}
        for index in range(3):
            tools = rg.ResearchTools(rg.SourceLedger(root / f"sources{index}.json"), root / f"pages{index}",
                                     search_fn=lambda query, n: payload, fetch_fn=lambda url: page)
            started = time.perf_counter()
            tools.fetch("https://grid.org/page", focus="capacity", agent_id="K1")
            runs["fetch"].append(time.perf_counter() - started)
            started = time.perf_counter()
            tools.search("grid capacity", agent_id="K1")
            runs["search"].append(time.perf_counter() - started)
        out = {name: min(values) for name, values in runs.items()}
    elif case == "boilerplate":
        label = "Related" + " " * 20_000 + "x"
        out["label"] = best(lambda: rg._is_boilerplate(label))
        page = "\n\n".join(["Sources", label, "Notes:" + "\t" * 20_000 + "!", "[" * 20_000,
                            "](" * 10_000, "Capacity reached 176 GW in 2023, up 12%."])
        out["select_passages"] = best(lambda: rg.select_passages(page, ["capacity"], 2_600))
        think = "<think>" * 20_000 + "Answer"
        out["strip_think"] = best(lambda: rg._strip_think(think))
    elif case == "quantity":
        for name, run in (("digits", "1" * 16_000), ("comma_groups", "1," * 8_000), ("dotted", "1." * 8_000)):
            entry = "- Table: " + run + "."
            prose = "Values: " + run + "."
            out[f"entry_{name}"] = best(lambda entry=entry: rg._is_citation_entry(entry))
            out[f"prose_{name}"] = best(lambda prose=prose: rg._reads_as_body_prose(prose))
            page = "Capacity reached 176 GW in 2023.\n\n1. " + run + "\n\n" + prose
            out[f"passages_{name}"] = best(lambda page=page: rg.select_passages(page, ["capacity"], 2_600))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=("whitespace", "tools", "boilerplate", "quantity"))
    args = parser.parse_args()
    print(json.dumps(_r3_timing_probe(args.case)))


if __name__ == "__main__":
    main()
