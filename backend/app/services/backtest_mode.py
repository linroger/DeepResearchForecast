"""Backtest mode, backend side (design: docs/handoff/backtest/design.md).

A backtest pipeline pins ``options["backtest_v1"]`` at admission: an as-of date,
strictness, the archive route, an ablation arm and, for golden-question runs, the
target question.  This module owns that object:

* :func:`normalize_backtest_request` validates an API/driver request (fail closed);
* :func:`research_child_policy` renders the research child's ``DRF_BACKTEST_POLICY``
  (the bridge's ``backtest_cutoff`` reads it);
* the arm accessors tell each stage what to switch: markets, the simulation's
  effect on probabilities, the world channel;
* :func:`policy_for_simulation` finds the pinned policy of the pipeline that owns a
  simulation (the report agent and the simulation config read it from there).

A pipeline without the option is a live run: every accessor returns ``None`` (or
the live default) and nothing changes.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

BACKTEST_OPTION = "backtest_v1"
BACKTEST_VERSION = "backtest/v1"
ARCHIVES = ("wayback", "off")

# Cumulative ablation arms (design §7).  ``simulation`` is whether the simulation
# may move published probabilities (Foglamp's evaluation-only ``legacy_prompt``)
# or must stay out of them entirely (``no_update``); ``production`` keeps the
# run's pinned live policy, i.e. measures the pipeline as configured today.
ARMS: dict[str, dict[str, Optional[bool]]] = {
    "research_only": {"markets": False, "simulation": False, "world_channel": False},
    "markets": {"markets": True, "simulation": False, "world_channel": False},
    "simulation": {"markets": True, "simulation": True, "world_channel": False},
    "world_channel": {"markets": True, "simulation": True, "world_channel": True},
    "production": {"markets": True, "simulation": None, "world_channel": True},
}
ABLATION_ARMS = ("research_only", "markets", "simulation", "world_channel")
DEFAULT_ARM = "production"

_GOLDEN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BacktestRequestError(ValueError):
    """A backtest request that must not be admitted."""


def _iso_day(value: Any, name: str) -> date:
    text = str(value or "").strip()
    if not _ISO_DAY_RE.match(text):
        raise BacktestRequestError(f"backtest {name} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise BacktestRequestError(f"backtest {name} is not a calendar date: {text}") from None


def normalize_backtest_request(raw: Any, *, today: Optional[date] = None) -> dict[str, Any]:
    """The ``backtest_v1`` option for a request, or :class:`BacktestRequestError`.

    ``as_of`` must be a past date (a cutoff of today or later is a live run);
    ``strict`` defaults to true, ``archive`` to ``wayback``, ``arm`` to
    ``production``.  A ``target`` (golden question) needs a question, and its
    resolution date, when given, must come after the as-of date.
    """
    if not isinstance(raw, Mapping):
        raise BacktestRequestError("backtest must be an object")
    unknown = sorted(set(raw) - {"as_of", "strict", "archive", "arm", "target", "run_label"})
    if unknown:
        raise BacktestRequestError(f"unknown backtest field(s): {', '.join(unknown)}")
    as_of = _iso_day(raw.get("as_of"), "as_of")
    current = today or datetime.now(timezone.utc).date()
    if as_of >= current:
        raise BacktestRequestError(f"backtest as_of must be before today ({current.isoformat()})")
    strict = raw.get("strict", True)
    if not isinstance(strict, bool):
        raise BacktestRequestError("backtest strict must be true or false")
    archive = str(raw.get("archive") or "wayback").strip().lower()
    if archive not in ARCHIVES:
        raise BacktestRequestError(f"backtest archive must be one of {', '.join(ARCHIVES)}")
    arm_name = str(raw.get("arm") or DEFAULT_ARM).strip()
    if arm_name not in ARMS:
        raise BacktestRequestError(f"backtest arm must be one of {', '.join(ARMS)}")
    option: dict[str, Any] = {
        "version": BACKTEST_VERSION, "as_of": as_of.isoformat(), "strict": strict, "archive": archive,
        "arm": {"name": arm_name, **ARMS[arm_name]},
        "target": None, "run_label": "",
        "pinned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    target = raw.get("target")
    if target is not None:
        if not isinstance(target, Mapping):
            raise BacktestRequestError("backtest target must be an object")
        golden_id = str(target.get("golden_id") or "").strip()
        question = " ".join(str(target.get("question") or "").split())
        if not _GOLDEN_ID_RE.match(golden_id):
            raise BacktestRequestError("backtest target golden_id must be a short lowercase id")
        if not question or len(question) > 1000:
            raise BacktestRequestError("backtest target question must be 1-1000 characters")
        criteria = " ".join(str(target.get("resolution_criteria") or "").split())[:2000]
        resolution = target.get("resolution_date")
        resolution_day = _iso_day(resolution, "target resolution_date") if resolution else None
        if resolution_day is not None and resolution_day <= as_of:
            raise BacktestRequestError("backtest target must resolve after the as-of date")
        option["target"] = {"golden_id": golden_id, "question": question, "resolution_criteria": criteria,
                            "resolution_date": resolution_day.isoformat() if resolution_day else None}
    label = raw.get("run_label")
    if label is not None:
        if not isinstance(label, str) or len(label) > 120:
            raise BacktestRequestError("backtest run_label must be a string of at most 120 characters")
        option["run_label"] = label.strip()
    return option


def backtest_of(options: Any) -> Optional[dict[str, Any]]:
    """The pinned option of a pipeline's options, ``None`` for a live run."""
    if not isinstance(options, Mapping):
        return None
    option = options.get(BACKTEST_OPTION)
    return option if isinstance(option, dict) and option.get("version") == BACKTEST_VERSION else None


def research_child_policy(option: Mapping[str, Any], *, audit_path: str) -> str:
    """``DRF_BACKTEST_POLICY`` for the research child (validated by the bridge's parser)."""
    payload = {"version": BACKTEST_VERSION, "as_of": option["as_of"], "strict": bool(option["strict"]),
               "archive": option["archive"], "audit_path": audit_path}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    from .official_data import bridge_module
    bridge_module("backtest_cutoff").parse_policy(text)  # the child's own parser must accept it
    return text


def markets_enabled(option: Optional[Mapping[str, Any]]) -> bool:
    """Whether the run may see prediction markets (always true for a live run)."""
    if not option:
        return True
    return bool((option.get("arm") or {}).get("markets", True))


def simulation_effect(option: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The simulation-forecast effect the arm imposes, ``None`` to keep the pinned one."""
    if not option:
        return None
    flag = (option.get("arm") or {}).get("simulation")
    if flag is None:
        return None
    return "legacy_prompt" if flag else "no_update"


def world_pressure_weight(option: Optional[Mapping[str, Any]]) -> Optional[float]:
    """``0.0`` when the arm turns the world channel off, ``None`` to keep the default."""
    if not option:
        return None
    return None if (option.get("arm") or {}).get("world_channel", True) else 0.0


def forecast_block(option: Mapping[str, Any]) -> dict[str, Any]:
    """The ``backtest`` block written into a backtest report's ``forecast.json``."""
    target = option.get("target") or {}
    return {"version": BACKTEST_VERSION, "as_of": option.get("as_of"), "strict": option.get("strict"),
            "archive": option.get("archive"), "arm": dict(option.get("arm") or {}),
            "golden_id": target.get("golden_id"), "run_label": option.get("run_label") or "",
            "production_ledger": "excluded"}


def is_backtest_forecast(forecast: Any) -> bool:
    """A ``forecast.json`` produced by a backtest run (never production evidence)."""
    return isinstance(forecast, Mapping) and isinstance(forecast.get("backtest"), Mapping)


def pipeline_for_simulation(simulation_id: Any) -> Optional[dict[str, Any]]:
    """Read the exact owner, including bound manual/secondary simulations.

    A verified consumed core is the only secondary-owner authority. Optional
    official datasets are checked by their own consumers; changed core proof
    cannot fall back to a mutable project or silently select live policy.
    Truly unbound legacy simulations retain the exact primary-ID lookup.
    """
    sid = str(simulation_id or "").strip()
    if not sid:
        return None
    from ..config import Config
    from .official_data import read_bound_research_core
    from .pipeline_orchestrator import PipelineManager
    proof = read_bound_research_core(sid)
    if proof["status"] == "invalid":
        raise ValueError("Simulation consumed research core proof is invalid")
    if proof["status"] == "valid":
        data = PipelineManager.load(proof["pipeline_id"])
        if (not isinstance(data, dict) or data.get("pipeline_id") != proof["pipeline_id"]
                or not isinstance(data.get("options"), dict)):
            raise ValueError("Bound simulation owner or pinned options are unavailable")
        if read_bound_research_core(sid) != proof:
            raise ValueError("Simulation consumed research changed while reading its owner")
        return deepcopy(data)
    root = Config.PIPELINE_DATA_DIR
    names = sorted(os.listdir(root)) if os.path.isdir(root) else []
    for pid in names:
        data = PipelineManager.load(pid)
        if isinstance(data, dict) and data.get("simulation_id") == sid:
            if not isinstance(data.get("options"), dict):
                raise ValueError("Simulation pinned options are invalid")
            return deepcopy(data)
    return None


def policy_for_simulation(simulation_id: Any) -> Optional[dict[str, Any]]:
    """Pinned backtest policy; invalid required proof never becomes live."""
    owner = pipeline_for_simulation(simulation_id)
    options = owner["options"] if owner else {}
    policy = backtest_of(options)
    if BACKTEST_OPTION in options and policy is None:
        raise ValueError("Simulation pinned backtest policy is invalid")
    if policy is not None:
        # A present saved arm must contain its complete admitted controls.
        # Accessor defaults are only for legacy/live callers, never a damaged pin.
        arm = policy.get("arm")
        name = arm.get("name") if isinstance(arm, dict) else None
        expected = ARMS.get(name) if isinstance(name, str) else None
        if (expected is None or set(arm) != {"name", *expected}
                or any(arm[key] is not value for key, value in expected.items())):
            raise ValueError("Simulation pinned backtest arm is invalid")
        _iso_day(policy.get("as_of"), "as_of")
        if not isinstance(policy.get("strict"), bool) or policy.get("archive") not in ARCHIVES:
            raise ValueError("Simulation pinned backtest cutoff controls are invalid")
    return policy
