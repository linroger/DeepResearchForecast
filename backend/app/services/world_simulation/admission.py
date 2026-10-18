"""Fresh pipeline admission only; saved runs must retain their existing pins.

This boundary reads an explicit non-secret operator profile when needed and
constructs/closes a strict HTTP client without dispatch. It creates no pipeline,
task, modeling receipt or world artifact. Compilation remains a later boundary.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import unicodedata

from .contracts import (
    DEFAULT_LIMITS, WorldError, canonical_json, clone, decimal, digest, quantity, require,
)
from .review import MODE_V4, candidate_repair_enabled, review_mode


UNSET = object()
_PROFILE_BYTES = 64 * 1024
_PROFILE_FIELDS = frozenset({"policy", "limits", "forecastEffect"})
_RAW_FIELDS = frozenset({
    "schemaVersion", "engine", "simulationId", "generationId", "forecastEffect", "actors",
    "periods", "asOf", "horizon", "initialState", "actionCatalog", "scheduledEvents", "flows",
    "assumptions", "sourceBindings", "seed", "limits", "gaps", "policy",
})
_SAFE_EFFECTS = frozenset({"diagnostic_only", "no_update"})


def _detached_object(value, *, fields, max_bytes):
    require(isinstance(value, dict), "invalid_world_request", "World input must be an object")
    try:
        encoded = canonical_json(value).encode("utf-8")
        require(set(value) <= fields, "invalid_world_request", "Unsupported world input fields")
        require(len(encoded) <= max_bytes, "invalid_world_request", "World input exceeds its size bound")
        return clone(value)
    except WorldError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise WorldError("invalid_world_request", "World input must be bounded JSON") from None


def _read_profile(profile_path):
    """Read at most 64 KiB; no component may be a symlink, even during open."""
    require(profile_path is not None and profile_path != "", "world_configuration_required",
            "Supply a world policy or configure WORLD_POLICY_SPEC_PATH")
    directory_fd = None
    file_fd = None
    try:
        path = Path(profile_path)
        parts = path.parts[1:] if path.is_absolute() else path.parts
        require(bool(parts), "invalid_world_profile", "World profile must be a regular JSON file")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        directory_fd = os.open(path.anchor if path.is_absolute() else ".", flags | os.O_DIRECTORY)
        for component in parts[:-1]:
            child_fd = os.open(component, flags | os.O_DIRECTORY, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        file_fd = os.open(parts[-1], flags, dir_fd=directory_fd)
        metadata = os.fstat(file_fd)
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= _PROFILE_BYTES,
                "invalid_world_profile", "World profile must be a regular file of at most 64 KiB")
        with os.fdopen(file_fd, "rb") as source:
            file_fd = None
            raw = source.read(_PROFILE_BYTES + 1)
        require(len(raw) <= _PROFILE_BYTES, "invalid_world_profile", "World profile exceeds 64 KiB")

        def pairs(items):
            result = {}
            for key, value in items:
                key = unicodedata.normalize("NFC", key)
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        def forbidden_number(_):
            raise ValueError("noninteger JSON number")

        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_float=forbidden_number, parse_constant=forbidden_number)
    except WorldError:
        raise
    except (OSError, TypeError, ValueError, RecursionError, OverflowError):
        raise WorldError("invalid_world_profile", "World profile cannot be read as bounded strict JSON") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _limits(value, *, complete):
    require(isinstance(value, dict) and set(value) <= set(DEFAULT_LIMITS),
            "invalid_limit", "World limits must contain only supported limit fields")
    if complete:
        require({"maxTokens", "maxCostUsd", "maxOutputTokens"} <= set(value),
                "invalid_modeling_budget", "Explicit token, USD and output ceilings are required")
    # validate_spec owns the same bounds, but also requires compiled actors and
    # identities unavailable at admission. Reuse its defaults, not a fake world.
    limits = {**DEFAULT_LIMITS, **value} if complete else clone(value)
    for key, limit in limits.items():
        if key == "maxCostUsd":
            require(isinstance(limit, str), "invalid_modeling_budget", "USD ceiling must be a decimal string")
            cost = decimal(limit, nonnegative=True)
            require(cost > 0, "invalid_modeling_budget", "USD ceiling must be positive")
            limits[key] = quantity(cost)
        else:
            require(type(limit) is int and 1 <= limit <= 10000000,
                    "invalid_limit", "World limits must be positive bounded integers")
    require(limits.get("maxActors", 20) <= 100 and limits.get("maxIntentsPerPhase", 3) <= 10
            and limits.get("maxAttemptsPerSlot", 2) == 2,
            "invalid_limit", "Fresh world actor, intent or two-attempt bounds are invalid")
    return limits


def _normalize_profile(value, *, complete, forecast_effect):
    from .compiler import _policy_metadata

    profile = _detached_object(value, fields=_PROFILE_FIELDS, max_bytes=_PROFILE_BYTES)
    if complete:
        require({"policy", "limits"} <= set(profile), "invalid_world_request",
                "World policy requires policy and limits")
        # Only absence inherits the captured snapshot; explicit null/conflicts
        # remain errors. Pin before hashing and before transport construction.
        profile.setdefault("forecastEffect", forecast_effect)
    if "limits" in profile:
        profile["limits"] = _limits(profile["limits"], complete=complete)
    if "policy" in profile:
        try:
            _policy_metadata(profile["policy"])
            mode = review_mode(profile)
        except WorldError as error:
            raise WorldError(error.code, "World policy metadata is invalid") from None
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
            raise WorldError("invalid_policy_metadata", "World policy metadata is invalid") from None
        require(mode == MODE_V4 or (not complete and mode is None),
                "invalid_policy_metadata", "Fresh world admission requires actor-consistency-v4")
        if complete:
            require(profile["policy"].get("responseFormat") == "json_object",
                    "invalid_policy_metadata", "Fresh world admission requires explicit json_object responses")
            require(candidate_repair_enabled(profile), "invalid_policy_metadata",
                    "Fresh world admission requires the known-output-error-v1 candidate repair pin")
    if "forecastEffect" in profile:
        effect = profile["forecastEffect"]
        require(isinstance(effect, str) and effect in _SAFE_EFFECTS and effect == forecast_effect,
                "unsupported_policy", "World forecast effect must match the safe pipeline snapshot")
    return profile


def _transport_ready(profile):
    from .policy import StrictHTTPModeler

    transport = None
    try:
        try:
            transport = StrictHTTPModeler(profile)
            # One declared request envelope per role (the modeler's own pin and
            # the shared actor envelope), not a forecast of the research-
            # dependent number of modeling or actor decisions.
            for max_input, max_output in {(transport.max_input, transport.max_output), transport.actor_envelope}:
                require(max_input + max_output <= profile["limits"]["maxTokens"],
                        "invalid_modeling_budget", "Declared request exceeds the total token ceiling")
                cost = decimal(transport._cost(max_input, max_output), nonnegative=True)
                require(cost <= decimal(profile["limits"]["maxCostUsd"], nonnegative=True),
                        "invalid_modeling_budget", "Declared request exceeds the total USD ceiling")
        finally:
            if transport is not None:
                transport.close()
    except WorldError as error:
        raise WorldError(error.code, "World HTTP policy or request budget is not ready") from None
    except Exception:
        raise WorldError("invalid_policy_client", "World HTTP policy configuration is not ready") from None


def resolve_fresh_simulation_request(
    *, mode, simulation_engine=UNSET, world_spec=None, world_policy_spec=None,
    max_rounds=None, forecast_effect="diagnostic_only", default_engine="oasis-legacy",
    profile_path=None,
):
    """Return detached launch options; never use this resolver for saved engines.

    Research-only validates explicit input shape/metadata but defers profile and
    authentication readiness. Full-world admission requires an explicitly pinned JSON
    policy with bounded candidate repair, pins an omitted effect from the safe
    snapshot, and refuses every calendar override. It checks one declared request
    envelope, not sufficient funding for the unknown future actor trajectory,
    and compiles no candidate.
    """
    require(isinstance(mode, str) and mode in {"full", "research_only"},
            "invalid_world_request", "Unsupported pipeline mode")
    engine = default_engine if simulation_engine is UNSET else simulation_engine
    require(isinstance(engine, str) and engine in {"oasis-legacy", "world-v1"},
            "unsupported_engine", "Unsupported simulation engine")
    raw = profile = None
    source = "legacy"
    complete = mode == "full"
    if engine == "oasis-legacy":
        require(world_spec is None and world_policy_spec is None, "invalid_world_request",
                "Legacy simulation does not accept world inputs")
    else:
        require(not complete or max_rounds is None, "world_calendar_override",
                "World periods are part of the model; max_rounds is not supported")
        require(isinstance(forecast_effect, str) and forecast_effect in _SAFE_EFFECTS,
                "unsupported_policy", "World admission requires a safe pipeline forecast policy")
        require(world_spec is None or world_policy_spec is None, "invalid_world_request",
                "Supply a raw world spec or a modeling policy, not both")
        source = "deferred"
        if world_spec is not None:
            source = "raw_spec"
            raw = _detached_object(world_spec, fields=_RAW_FIELDS, max_bytes=2 * 1024 * 1024)
            profile = _normalize_profile(
                {key: raw[key] for key in _PROFILE_FIELDS if key in raw},
                complete=complete, forecast_effect=forecast_effect,
            )
            raw.update(clone(profile))
        elif world_policy_spec is not None or complete:
            source = "request_policy" if world_policy_spec is not None else "operator_profile"
            value = world_policy_spec if world_policy_spec is not None else _read_profile(profile_path)
            profile = _normalize_profile(value, complete=complete, forecast_effect=forecast_effect)
        if complete:
            _transport_ready(profile)

    admission = {
        "version": "simulation-admission/v1", "source": source,
        "status": "deferred" if engine == "world-v1" and not complete else "ready",
    }
    if profile is not None:
        admission["profile_sha256"] = digest(profile)
    return {
        "simulation_engine": engine, "world_spec": raw,
        "world_policy_spec": profile if raw is None else None,
        "simulation_admission_v1": admission,
    }
