"""Admitted forecast objective and executable-calendar invariants.

Horizon interpretation happens once in PREPARE. The resulting typed objective is
sealed with the config; consumers check it instead of interpreting prose again.
Hashes bind inputs, not semantic truth or an adversary-controlled replacement.
"""
from __future__ import annotations

from datetime import date, timedelta
from dataclasses import asdict
import hashlib
import json
from typing import Any

KEY = "forecast_task_v1"
VERSION = "forecast-task/v1"


class ForecastTaskError(ValueError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def execution_config_fingerprint(config: dict) -> str:
    """Keep the existing simulation checkpoint fingerprint byte-compatible."""
    return hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


def _date(value: Any, field: str) -> date:
    try:
        if not isinstance(value, str):
            raise ValueError()
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise ForecastTaskError(f"forecast task {field} must be an ISO calendar date") from None


def bind_task(requirement: str, timeline: dict, *, central_question: str = "",
              declared_horizon: str = "", round_limit: int = 48, semantic_review: dict | None = None) -> dict:
    """Bind one resolved objective to its complete inputs and resolution basis."""
    as_of = _date(timeline.get("as_of_date"), "as_of_date")
    horizon = _date(timeline.get("horizon_date"), "horizon_date")
    if horizon <= as_of:
        raise ForecastTaskError("forecast horizon must follow the baseline")
    evidence = str(timeline.get("horizon_text") or "")
    method = str(timeline.get("horizon_source") or "")
    defaulted = timeline.get("horizon_defaulted")
    inputs = {"requirement": str(requirement or ""), "as_of_date": as_of.isoformat(),
              "central_question": str(central_question or ""), "declared_horizon": str(declared_horizon or ""),
              "baseline_defaulted": "as_of_defaulted" in (timeline.get("warnings") or [])}
    if type(defaulted) is not bool or not method:
        raise ForecastTaskError("forecast task resolution provenance is missing")
    if defaulted or method == "default":
        raise ForecastTaskError("forecast endpoint is unresolved; provide an explicit task horizon")
    if type(round_limit) is not int or round_limit < 1:
        raise ForecastTaskError("forecast task round limit must be a positive integer")
    if method not in {"explicit_date", "anchored_period", "relative", "bare_year", "llm"}:
        raise ForecastTaskError("forecast task resolution method is unsupported")
    from ..utils.sim_timeline import _add_months
    if horizon > _add_months(as_of, 360):
        raise ForecastTaskError("forecast endpoint is outside the supported task window")
    if method != "default" and (not evidence or not any(
            evidence in inputs[key] for key in ("requirement", "central_question", "declared_horizon"))):
        raise ForecastTaskError("forecast horizon resolution needs an exact task-source quote")
    if (method == "default") != defaulted:
        raise ForecastTaskError("forecast task default policy is inconsistent")
    if method != "llm":
        from ..utils.sim_timeline import extract_horizon
        resolved = extract_horizon(evidence, as_of)
        if resolved is None or resolved.horizon_date != horizon.isoformat():
            raise ForecastTaskError("forecast endpoint does not match its quoted date evidence")
    else:
        review = semantic_review
        if (not isinstance(review, dict) or review.get("inputs_sha256") != _sha(inputs)
                or review.get("horizon_date") != horizon.isoformat()
                or review.get("source_quote") != evidence
                or review.get("source_field") not in {"requirement", "central_question", "declared_horizon"}
                or evidence not in inputs[review["source_field"]]
                or review.get("faithful") is not True or review.get("complete") is not True
                or review.get("issues") != []):
            raise ForecastTaskError("forecast objective lacks complete source-bound semantic review")
    task = {"schema_version": VERSION, "inputs": inputs, "inputs_sha256": _sha(inputs),
            "horizon_date": horizon.isoformat(), "round_limit": round_limit,
            "resolution": {"method": method, "source_quote": evidence, "defaulted": defaulted}}
    if method == "llm":
        task["resolution"]["semantic_review"] = semantic_review
    task["task_sha256"] = _sha(task)
    return task


def validate_task_calendar(config: dict) -> dict | None:
    """Reject a changed objective, calendar or world clock before execution.

    An absent marker remains an explicit legacy path. Present invalid markers
    cannot downgrade to hours mode or acquire a newly inferred endpoint.
    """
    if not isinstance(config, dict):
        raise ForecastTaskError("simulation config must be an object")
    if KEY not in config:
        return None
    task = config[KEY]
    if not isinstance(task, dict) or task.get("schema_version") != VERSION:
        raise ForecastTaskError("forecast task contract is missing or unsupported")
    body = {k: v for k, v in task.items() if k != "task_sha256"}
    if task.get("task_sha256") != _sha(body):
        raise ForecastTaskError("forecast task fingerprint mismatch")
    inputs = task.get("inputs")
    if not isinstance(inputs, dict) or task.get("inputs_sha256") != _sha(inputs):
        raise ForecastTaskError("forecast task inputs changed")
    if config.get("simulation_requirement") != inputs.get("requirement"):
        raise ForecastTaskError("simulation question differs from admitted forecast task")
    calendar = config.get("temporal_config")
    if not isinstance(calendar, dict) or calendar.get("mode") != "calendar":
        raise ForecastTaskError("admitted forecast task requires its calendar")
    baseline = _date(inputs.get("as_of_date"), "as_of_date")
    endpoint = _date(task.get("horizon_date"), "horizon_date")
    if config.get("as_of_date") != baseline.isoformat() or calendar.get("as_of_date") != baseline.isoformat():
        raise ForecastTaskError("simulation baseline differs from admitted forecast task")
    if calendar.get("horizon_date") != endpoint.isoformat() or endpoint <= baseline:
        raise ForecastTaskError("calendar endpoint differs from admitted forecast task")
    rebuilt = bind_task(inputs["requirement"], calendar, central_question=inputs.get("central_question", ""),
                        declared_horizon=inputs.get("declared_horizon", ""), round_limit=task.get("round_limit"),
                        semantic_review=(task.get("resolution") or {}).get("semantic_review"))
    if rebuilt != task:
        raise ForecastTaskError("calendar resolution differs from admitted forecast task")
    periods = calendar.get("round_dates")
    count = calendar.get("n_rounds")
    if not isinstance(periods, list) or not periods or type(count) is not int or count != len(periods):
        raise ForecastTaskError("calendar round count does not match its period coverage")
    if count > task["round_limit"]:
        raise ForecastTaskError("calendar exceeds the admitted round budget")
    from ..utils.sim_timeline import UNIT_ORDER, build_round_periods
    unit, stride = calendar.get("unit"), calendar.get("unit_stride")
    if unit not in UNIT_ORDER or type(stride) is not int or stride < 1:
        raise ForecastTaskError("calendar unit or stride is invalid")
    expected_periods = [asdict(row) for row in build_round_periods(baseline, endpoint, unit, stride)]
    if periods != expected_periods:
        raise ForecastTaskError("calendar periods differ from their declared time unit")
    cursor = baseline + timedelta(days=1)
    for index, period in enumerate(periods):
        if not isinstance(period, dict) or type(period.get("round")) is not int or period["round"] != index:
            raise ForecastTaskError("calendar round identities are not contiguous")
        start = _date(period.get("period_start"), "period_start")
        end = _date(period.get("period_end"), "period_end")
        if start != cursor or end < start or end > endpoint:
            raise ForecastTaskError("calendar has a gap, overlap or out-of-task period")
        cursor = end + timedelta(days=1)
    if cursor != endpoint + timedelta(days=1):
        raise ForecastTaskError("calendar does not cover the admitted forecast endpoint")
    for key in ("world_model", "world_state_seed"):
        if key in config:
            world = config[key]
            if not isinstance(world, dict) or not world:
                raise ForecastTaskError(f"present {key} is not an executable world block")
            if world.get("horizon_date") != endpoint.isoformat():
                raise ForecastTaskError(f"{key} endpoint differs from admitted forecast task")
            if world.get("as_of_date") != baseline.isoformat():
                raise ForecastTaskError(f"{key} baseline differs from admitted forecast task")
            if key == "world_model":
                from .world_model_seed import WORLD_MODEL_SEED_VERSION
                if (world.get("schema_version") != WORLD_MODEL_SEED_VERSION
                        or not all(isinstance(world.get(field), list) for field in ("state_variables", "actors", "relationships"))
                        or not isinstance(world.get("settings"), dict)):
                    raise ForecastTaskError("present world_model does not implement the executable world schema")
    return task


def validate_task_trajectory(config: dict, trajectory: Any) -> None:
    """A task-bound report may use only the completed matching clock history."""
    task = validate_task_calendar(config)
    if task is None:
        return
    calendar = config["temporal_config"]
    if (not isinstance(trajectory, dict) or trajectory.get("mode") != "calendar"
            or trajectory.get("forecast_task_sha256") != task["task_sha256"]
            or trajectory.get("config_hash") != execution_config_fingerprint(config)
            or trajectory.get("horizon_date") != task["horizon_date"]
            or trajectory.get("calendar_unit") != calendar["unit"]):
        raise ForecastTaskError("report trajectory differs from admitted forecast task")
    baseline = task["inputs"]["as_of_date"]
    for key in ("as_of_date", "as_of"):
        if key in trajectory and trajectory[key] != baseline:
            raise ForecastTaskError("report trajectory baseline differs from admitted task")
    rows = trajectory.get("trajectory")
    if (not isinstance(rows, list) or len(rows) != calendar["n_rounds"] + 1
            or type(trajectory.get("n_rounds")) is not int
            or trajectory.get("n_rounds") != calendar["n_rounds"]
            or not isinstance(rows[0], dict) or type(rows[0].get("round")) is not int
            or rows[0].get("round") != 0 or rows[0].get("as_of") != baseline):
        raise ForecastTaskError("report trajectory does not cover the admitted task clock")
    for index, (row, period) in enumerate(zip(rows[1:], calendar["round_dates"]), 1):
        if (not isinstance(row, dict) or type(row.get("round")) is not int or row["round"] != index
                or row.get("period_start") != period["period_start"] or row.get("period_end") != period["period_end"]
                or row.get("as_of") != period["period_end"]):
            raise ForecastTaskError("report trajectory has a mismatched period clock")
