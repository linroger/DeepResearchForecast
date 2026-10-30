"""Source-reviewed off-mode comparison across historical, main and merged trees."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.fixtures.world_anchor_off_probe import capture_off_snapshot

FIXTURES = Path(__file__).with_name("fixtures")


def _load(name):
    return json.loads((FIXTURES / f"world_anchor_off_{name}.json").read_text())


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _apply_reviewed_delta(payload, changes, sources):
    """Apply exact before/after values; an unknown path or changed input fails closed."""
    result = deepcopy(payload)
    seen = set()
    for change in changes:
        path = change["path"]
        assert path not in seen, f"duplicate reviewed path: {path}"
        seen.add(path)
        assert change["source_refs"] and all(ref in sources for ref in change["source_refs"])
        parts = path.removeprefix("/").split("/")
        parent = result
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
        if change["op"] == "add":
            assert isinstance(parent, dict) and key not in parent, f"add already exists: {path}"
            parent[key] = deepcopy(change["value"])
        else:
            assert change["op"] == "replace", f"unreviewed operation: {change['op']}"
            assert parent[key] == change["old"], f"reviewed input changed: {path}"
            parent[key] = deepcopy(change["value"])
    return result


def assert_off_mode_compatible(receipt, *, historical_sha256):
    """Check complete payloads from two independent baselines, without exclusions."""
    historical, main, delta = (_load(name) for name in ("historical", "main", "reviewed_delta"))
    assert historical["sha256"] == historical_sha256 == delta["historical_sha256"]
    assert _digest(historical["payload"]) == historical_sha256
    assert _digest(main["payload"]) == main["sha256"] == delta["main_sha256"]
    expected_main = _apply_reviewed_delta(main["payload"], delta["main_to_merged"], delta["source_refs"])
    expected_historical = _apply_reviewed_delta(historical["payload"], delta["historical_to_merged"], delta["source_refs"])
    assert expected_main == expected_historical
    assert receipt["payload"] == expected_main
    assert _digest(receipt["payload"]) == receipt["sha256"] == delta["merged_sha256"]
    # Main's task changes require no new world-state or RNG mutation in this probe.
    assert receipt["payload"]["world"] == historical["payload"]["world"]
    assert receipt["payload"]["rng"] == main["payload"]["rng"] == historical["payload"]["rng"]


def test_off_matches_reviewed_main_and_historical_payloads_without_anchor_calls(monkeypatch):
    from app.services import actor_context, world_model_seed

    anchor_calls = []

    def unexpected_anchor(*args, **kwargs):
        anchor_calls.append((args, kwargs))
        raise AssertionError("off mode invoked an anchor projection")

    monkeypatch.setattr(world_model_seed, "build_anchor_runtime_projection", unexpected_anchor)
    monkeypatch.setattr(actor_context, "build_anchor_actor_payload", unexpected_anchor)
    receipt = capture_off_snapshot(monkeypatch)
    main = _load("main")
    assert not anchor_calls
    assert receipt["generator_instance_count"] == 1
    # Includes task extraction, independent review, event config and actor config.
    assert len(receipt["generator_calls"]) == 4
    assert receipt["generator_calls"] == main["generator_calls"]
    assert len(receipt["payload"]["calls"]) == 1
    assert receipt["rng_before"] == main["rng_before"] == receipt["payload"]["rng"]
    assert_off_mode_compatible(receipt, historical_sha256=
        "960d2466fff5be6edc329df3972728dbbac5600280252479999b22e91e478e92")
    root = os.environ.get("MAIN_OFFLINE_EVIDENCE")
    if root:
        (Path(root) / "off-mode-main-comparison.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("invalid", ["unsupported_source_quote", "rejected_semantic_review"])
def test_off_task_still_requires_supported_source_and_independent_review(monkeypatch, invalid):
    from app.services.forecast_task import ForecastTaskError

    def corrupt(prompt, reply):
        if invalid == "unsupported_source_quote" and prompt.startswith("FORECAST TASK EXTRACTION\n"):
            return {**reply, "source_quote": "THIS DATE DOES NOT APPEAR IN THE REQUIREMENT"}
        if invalid == "rejected_semantic_review" and prompt.startswith("FORECAST TASK REVIEW\n"):
            return {"faithful": False, "complete": False, "issues": ["unsupported endpoint"]}
        return reply

    message = "lacks exact source evidence" if invalid == "unsupported_source_quote" else "failed independent semantic review"
    with pytest.raises(ForecastTaskError, match=message):
        capture_off_snapshot(monkeypatch, task_reply_transform=corrupt)
