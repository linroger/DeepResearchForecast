"""Offline model responses for explicit task fixtures, never production parsing.

This oracle accepts only simple declared horizons/ISO dates supplied by fixtures.
Ambiguous natural-language tasks require a fixture-specific expected candidate.
The review compares the candidate to the fixture oracle rather than returning
unconditional approval.
"""
import json
import re


def task_protocol(prompt, expected=None):
    if not prompt.startswith(("FORECAST TASK EXTRACTION\n", "FORECAST TASK REVIEW\n")):
        return None
    payload, _ = json.JSONDecoder().raw_decode(prompt.split("\n", 1)[1])
    review = prompt.startswith("FORECAST TASK REVIEW\n")
    inputs = payload["inputs"] if review else payload
    if expected is None:
        expected = {"horizon_date": None, "source_field": "requirement", "source_quote": ""}
        declared = inputs.get("declared_horizon", "")
        matched = re.fullmatch(r"(?:through |by )?(20\d{2})(?:-(\d\d)-(\d\d))?", declared)
        if matched:
            endpoint = f"{matched[1]}-{matched[2] or '12'}-{matched[3] or '31'}"
            expected = {"horizon_date": endpoint, "source_field": "declared_horizon", "source_quote": declared}
        else:
            matches = re.findall(r"(?<!\d)20\d{2}-\d\d-\d\d(?!\d)", inputs.get("requirement", ""))
            if len(matches) == 1:
                expected = {"horizon_date": matches[0], "source_field": "requirement", "source_quote": matches[0]}
    if not review:
        return expected
    ok = expected["horizon_date"] is not None and payload["candidate"] == expected
    return {"faithful": ok, "complete": ok, "issues": [] if ok else ["fixture objective mismatch"]}
