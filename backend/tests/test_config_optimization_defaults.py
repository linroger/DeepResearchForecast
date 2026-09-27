"""Regression guard for the optimization-pass config defaults.

These assert the *in-code* defaults baked into ``app.config.Config`` for the
speed + calibration optimization pass (CHUNK-1, GRAPH-1/3/4/6/9, SIM-2/3, the
REPORT-* report knobs, the R2-CAL calibration keystones, etc.).

Why a subprocess: ``app.config`` calls ``load_dotenv(override=True)`` at import
time, so the developer's local ``.env`` would mask the code defaults (e.g. a
machine that pins ``OASIS_SEMAPHORE=16``). To test what ships in the repo we
re-import the module in a clean child process with ``.env`` loading neutralized
and the relevant env vars stripped, so ``os.environ.get(FLAG, DEFAULT)`` falls
through to ``DEFAULT`` every time.
"""

import json
import os
import subprocess
import sys

# Pinned defaults from the optimization config spec (config bucket).
EXPECTED = {
    # CHUNK-1 / GRAPH-2 / ONTO-1 / ONTO-2 / RESEARCH-1
    "DEFAULT_CHUNK_SIZE": 2500,
    "DEFAULT_CHUNK_OVERLAP": 250,
    # GRAPH build concurrency + intra-episode fan-out + executors (GRAPH-1/3, R2-EXEC-1/2)
    "GRAPH_BUILD_CONCURRENCY": 4,
    "GRAPHITI_MAX_COROUTINES": 16,
    "GRAPH_LLM_EXECUTOR_WORKERS": 64,
    "EMBED_EXECUTOR_WORKERS": 4,
    "GRAPH_MAX_NODES": 8000,  # GRAPH-6
    "GRAPH_RESOLVE_ENTITIES": True,  # GRAPH-4
    "GRAPH_RESOLVE_SIM_THRESHOLD": 0.88,
    "GRAPHITI_OP_TIMEOUT_S": 900.0,  # GRAPH-9
    "ZEP_MAX_RETRIES": 2,  # GRAPH-9 / GRAPH-11
    # LLM routing / cache / tuned HTTP client
    "LLM_TIERED_ROUTING": True,  # GAP-1
    "LLM_CACHE_ENABLED": True,  # SIM-9 / CACHE-1
    "LLM_HTTP2": True,  # R2-EXEC-6
    "LLM_HTTP_KEEPALIVE": 128,
    # Report knobs
    "REPORT_SECTION_CONCURRENCY": 6,  # REPORT-1 (3) → PAR-3 (6)
    "REPORT_SECTION_CONTEXT_MODE": "brief",  # REPORT-2
    "REPORT_SIGNAL_PACK": True,  # REPORT-3
    "REPORT_NATIVE_TOOLS": True,  # REPORT-4
    "REPORT_AGENT_TOOL_TURN_MAX_TOKENS": 8192,  # REPORT-9
    # Sim
    "OASIS_DEFAULT_MAX_ROUNDS": 36,  # SIM-2
    "OASIS_SEMAPHORE": 24,  # SIM-3
    "PROFILE_ZEP_SKIP_WHEN_CONTEXT": True,  # SIM-7
    "IPC_TELEMETRY_ENABLED": True,  # SIM-12 / OBS-1
    "SIM_DECISION_CHANNEL": True,  # R2-SIM-1 / R2-CAL-3
    "SIM_CONVERGENCE_STOP": True,  # SIM-1
    # Ontology
    "ONTOLOGY_AUTO_SELECT": True,  # ONTO-4
    # Calibration keystones (R2-CAL) — Foglamp WP1 (1D) containment defaults:
    # single spine draw, identity extremization (an extremize>1 is a forecast
    # policy that must pass WP14 outcome-blind promotion before overriding).
    "FORECAST_PROB_FLOOR": 0.03,
    "REPORT_SPINE_SELFCONSISTENCY_K": 1,
    "ENSEMBLE_EXTREMIZE_A": 1.0,
    "REPORT_SPINE_ANCHOR_WORLDSTATE": True,
    # LOOP-017 P0 market-influence boundary: only matches at/above this confidence
    # may move a published probability toward a market (display anchoring is not gated).
    "FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE": 0.6,
    # Research
    "RESEARCH_QUALITY_FLOOR": 0.45,  # R2-RES-1
    # Deep-research engine v3 is the shipped default (legacy stays opt-in).
    "RESEARCH_ENGINE": "v3",
}

# Child program: neutralize .env, strip flag keys, import Config, dump values.
_CHILD = r"""
import json, os, sys
import dotenv
dotenv.load_dotenv = lambda *a, **k: False  # neutralize repo .env override
keys = json.loads(sys.argv[1])
for k in keys:
    os.environ.pop(k, None)
from app.config import Config
out = {k: getattr(Config, k) for k in keys}
print("<<<JSON>>>" + json.dumps(out))
"""

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_code_defaults():
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_")
           and not k.startswith("GRAPH") and not k.startswith("OASIS")
           and not k.startswith("REPORT") and not k.startswith("SIM")
           and not k.startswith("FORECAST") and not k.startswith("ENSEMBLE")
           and not k.startswith("ONTOLOGY") and not k.startswith("RESEARCH")
           and not k.startswith("IPC") and not k.startswith("PROFILE")
           and not k.startswith("ZEP") and not k.startswith("EMBED")
           and not k.startswith("DEFAULT_CHUNK")}
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, json.dumps(list(EXPECTED.keys()))],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"child failed: {proc.stderr}\n{proc.stdout}"
    marker = "<<<JSON>>>"
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith(marker)]
    assert line, f"no JSON marker in child output:\n{proc.stdout}"
    return json.loads(line[-1][len(marker):])


def test_optimization_defaults_match_spec():
    got = _load_code_defaults()
    mismatches = {k: (got.get(k), EXPECTED[k]) for k in EXPECTED if got.get(k) != EXPECTED[k]}
    assert not mismatches, f"config default drift (got, expected): {mismatches}"


def test_degrade_safe_invariants():
    """Defaults must keep the pipeline runnable end-to-end.

    The risky parallel-build knob (GRAPH_BUILD_CONCURRENCY>1) MUST ship paired
    with the entity-resolution dedup safety net, and round/cost caps must be
    finite so a flipped-on decision channel cannot run unbounded.
    """
    got = _load_code_defaults()
    if got["GRAPH_BUILD_CONCURRENCY"] > 1:
        assert got["GRAPH_RESOLVE_ENTITIES"] is True, (
            "parallel graph build must pair with GRAPH_RESOLVE_ENTITIES dedup net"
        )
    # Decision channel is on by default; it must be bounded by a finite round cap.
    if got["SIM_DECISION_CHANNEL"]:
        assert got["OASIS_DEFAULT_MAX_ROUNDS"] > 0, (
            "SIM_DECISION_CHANNEL on requires a finite OASIS_DEFAULT_MAX_ROUNDS cap"
        )
    # Bounded op timeout so a wedged graphiti op fails fast instead of hanging.
    assert got["GRAPHITI_OP_TIMEOUT_S"] > 0
    # Probability floor in the open interval (never publish 0%, never a degenerate floor).
    assert 0 < got["FORECAST_PROB_FLOOR"] < 0.5
    assert got["REPORT_SPINE_SELFCONSISTENCY_K"] >= 1
