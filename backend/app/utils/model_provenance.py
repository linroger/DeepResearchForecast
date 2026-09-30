"""INFRA-8: model provenance, i.e. which model each stage asked for and which model served it.

Pure helpers (stdlib only, no Config import) shared by LLMClient and LLMMeter (the per-call
requested label and served id), the pipeline orchestrator (run.json ``resolved`` stamps and
the report's ``run_provenance``) and ReportAgent (forecast.json ``model_provenance``).

Vocabulary:

- requested label: the model a call asked for, as the transport actually sends it
  (:func:`effective_model_label`). A CLI provider that is not given ``--model`` runs on its
  account default model, recorded as ``cli-default``.
- served id: the model the provider reported serving the call (the OpenAI-compatible
  ``response.model``, the Claude CLI result envelope, LangChain ``response_metadata``).
  Providers that report nothing leave it None; such calls count in ``calls`` only.

Served ids are counted per requested label and capped at MAX_SERVED_IDS distinct ids;
further new ids count under OTHER_SERVED_KEY, so a gateway that echoes a fresh snapshot id
per call cannot grow a telemetry artifact without bound.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Mapping, Optional

MODEL_PROVENANCE_VERSION = "model-provenance/v1"
CLI_DEFAULT_LABEL = "cli-default"
UNKNOWN_MODEL_LABEL = "unknown"
MAX_SERVED_IDS = 16
OTHER_SERVED_KEY = "_other"
REPORT_STAGE = "report"

# run.json ``resolved`` block that carries each pipeline stage's model provenance. Mirrors
# run_shape.RESOLVED_BLOCK_FOR_STAGE (RUN's block is "simulation") plus PREPARE, whose
# block only INFRA-8 writes (see EXTRA_RESOLVED_BLOCKS).
RESOLVED_BLOCK_FOR_STAGE: Dict[str, str] = {
    "research": "research",
    "ontology": "ontology",
    "graph": "graph",
    "prepare": "prepare",
    "run": "simulation",
    "report": "report",
}
# run.json blocks written only by INFRA-8. run_shape.carry_forward_resolved does not know
# them, so the attempt-start fold carries them with carry_forward_extra_blocks().
EXTRA_RESOLVED_BLOCKS = ("prepare",)
# Keys of a resolved block that describe models (the forecast.json ``stages`` subset).
PROVENANCE_KEYS = ("provider", "model_name", "model", "model_id", "requested_model", "served_models")

_CLAUDE_ALIASES = ("opus", "sonnet", "haiku")


def claude_cli_model_arg(model: Optional[str]) -> Optional[str]:
    """The ``--model`` value the Claude CLI is given for ``model``, or None (the CLI then runs
    on the account's default model).

    Only claude model ids/aliases pass through; anything else (e.g. another provider's
    LLM_MODEL_NAME inherited by a claude-cli client) is dropped defensively. Callers that
    attribute output to a model (the eval judge identity) use this to record the model the
    CLI was actually asked for rather than ``LLMClient.model``.
    """
    m = (model or "").strip()
    if m and (m.startswith("claude") or m in _CLAUDE_ALIASES):
        return m
    return None


def effective_model_label(provider: Optional[str], model: Optional[str]) -> str:
    """The model a call to ``provider`` actually requests for ``model``.

    claude-cli: the model when it is passed via ``--model`` (claude_cli_model_arg), else
    ``cli-default``. codex-cli is never given a model: always ``cli-default``. Any other
    provider sends ``model`` itself (``unknown`` when there is none).
    """
    p = (provider or "").strip().lower()
    if p == "claude-cli":
        return claude_cli_model_arg(model) or CLI_DEFAULT_LABEL
    if p == "codex-cli":
        return CLI_DEFAULT_LABEL
    m = str(model).strip() if model is not None else ""
    return m or UNKNOWN_MODEL_LABEL


def served_models_from_claude_envelope(env: Any) -> List[str]:
    """Model ids a Claude CLI JSON result envelope reports under ``modelUsage`` (its keys, in
    envelope order). [] when the envelope has no such map."""
    if not isinstance(env, Mapping):
        return []
    usage = env.get("modelUsage")
    if not isinstance(usage, Mapping):
        return []
    return [name for name in usage if isinstance(name, str) and name.strip()]


def _count(value: Any) -> int:
    """A non-negative call count (bools, junk and negatives count as 0)."""
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def count_served(served: Dict[str, int], served_id: Any, calls: int = 1) -> None:
    """Add ``calls`` calls served by ``served_id`` to ``served`` ({id: calls}) in place.

    At most MAX_SERVED_IDS distinct ids are kept; a new id beyond the cap counts under
    OTHER_SERVED_KEY. A missing or blank id is not counted (the caller still counts the call).
    """
    if not isinstance(served_id, str) or not served_id.strip() or calls <= 0:
        return
    sid = served_id.strip()
    if sid not in served and sum(1 for key in served if key != OTHER_SERVED_KEY) >= MAX_SERVED_IDS:
        sid = OTHER_SERVED_KEY
    served[sid] = served.get(sid, 0) + calls


def merge_served(into: Dict[str, int], served: Any) -> None:
    """Add a ``{id: calls}`` map into ``into`` (same cap as count_served)."""
    if not isinstance(served, Mapping):
        return
    for sid, calls in served.items():
        count_served(into, sid, _count(calls))


def served_model_list(served: Any) -> List[str]:
    """Served ids of a ``{id: calls}`` map, most calls first (ties by id), OTHER_SERVED_KEY last."""
    if not isinstance(served, Mapping):
        return []
    ids = [sid for sid in served if isinstance(sid, str) and sid != OTHER_SERVED_KEY]
    ids.sort(key=lambda sid: (-_count(served.get(sid)), sid))
    if OTHER_SERVED_KEY in served:
        ids.append(OTHER_SERVED_KEY)
    return ids


def stage_served_models(model_resolution: Any, stage: str) -> List[str]:
    """Served ids of ``stage`` in an LLMMeter snapshot's ``model_resolution`` (every requested
    label of the stage merged). [] when the stage recorded none."""
    if not isinstance(model_resolution, Mapping):
        return []
    entries = model_resolution.get(stage)
    if not isinstance(entries, Mapping):
        return []
    served: Dict[str, int] = {}
    for entry in entries.values():
        if isinstance(entry, Mapping):
            merge_served(served, entry.get("served"))
    return served_model_list(served)


def stage_record(provider: Optional[str], model: Optional[str], model_resolution: Any,
                 stage: str) -> Dict[str, Any]:
    """``{requested_model, served_models}`` of one stage: the effective label of the stage's
    provider/model and the ids the meter saw served for that stage."""
    return {
        "requested_model": effective_model_label(provider, model),
        "served_models": stage_served_models(model_resolution, stage),
    }


def merge_research_model_resolutions(parts: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """Merge research children's ``meta.model_resolution`` blocks (parallel lanes plus the
    global synthesis) into one: the first reported model / model_id win, per-model calls and
    served counts are summed. None when no part is a mapping."""
    out: Optional[Dict[str, Any]] = None
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        if out is None:
            out = {"model": None, "model_id": None, "models": {}}
        for key in ("model", "model_id"):
            value = part.get(key)
            if out[key] is None and isinstance(value, str) and value:
                out[key] = value
        models = part.get("models")
        if not isinstance(models, Mapping):
            continue
        for name, entry in models.items():
            if not isinstance(entry, Mapping):
                continue
            dst = out["models"].setdefault(str(name), {"calls": 0, "served": {}})
            dst["calls"] += _count(entry.get("calls"))
            merge_served(dst["served"], entry.get("served"))
    return out


def research_stage_record(model_resolution: Any) -> Dict[str, Any]:
    """``{model_id, served_models}`` for run.json ``resolved.research`` from the research
    child's ``meta.model_resolution`` (None / [] when it reported none)."""
    resolution = model_resolution if isinstance(model_resolution, Mapping) else {}
    served: Dict[str, int] = {}
    models = resolution.get("models")
    if isinstance(models, Mapping):
        for entry in models.values():
            if isinstance(entry, Mapping):
                merge_served(served, entry.get("served"))
    model_id = resolution.get("model_id")
    return {
        "model_id": model_id if isinstance(model_id, str) and model_id else None,
        "served_models": served_model_list(served),
    }


def carry_forward_extra_blocks(prior_resolved: Any, resolved: Dict[str, Any]) -> None:
    """Copy the EXTRA_RESOLVED_BLOCKS the previous run.json holds into ``resolved`` (in place)
    when ``resolved`` lacks them, so a reused stage keeps its stamp across attempts."""
    if not isinstance(prior_resolved, Mapping):
        return
    for block_name in EXTRA_RESOLVED_BLOCKS:
        block = prior_resolved.get(block_name)
        if isinstance(block, Mapping) and block_name not in resolved:
            resolved[block_name] = copy.deepcopy(dict(block))


def run_provenance(resolved: Any, pin_drift: Any) -> Dict[str, Any]:
    """The ``run_provenance`` the orchestrator hands the report stage's ReportAgent.

    ``stages`` holds the PROVENANCE_KEYS of every upstream stage's run.json resolved block
    (research, ontology, graph, prepare, run), keyed by pipeline stage. REPORT is left out:
    at construction its stamp still describes a previous attempt's report, so ReportAgent
    fills it itself. ``pin_drift`` is the run-shape drift of this attempt (None without one).
    """
    stages: Dict[str, Any] = {}
    blocks = resolved if isinstance(resolved, Mapping) else {}
    for stage, block_name in RESOLVED_BLOCK_FOR_STAGE.items():
        if stage == REPORT_STAGE:
            continue
        block = blocks.get(block_name)
        if not isinstance(block, Mapping):
            continue
        subset = {key: copy.deepcopy(block[key]) for key in PROVENANCE_KEYS if key in block}
        if subset:
            stages[stage] = subset
    return {
        "version": MODEL_PROVENANCE_VERSION,
        "stages": stages,
        "pin_drift": copy.deepcopy(pin_drift) if pin_drift else None,
    }


def forecast_model_provenance(run_prov: Any, report_stage: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """forecast.json ``model_provenance``: a copy of ``run_prov`` whose ``stages`` gains the
    report stage record. None when ``run_prov`` is not a mapping (the key is then omitted)."""
    if not isinstance(run_prov, Mapping):
        return None
    out = copy.deepcopy(dict(run_prov))
    stages = out.get("stages")
    stages = dict(stages) if isinstance(stages, Mapping) else {}
    stages[REPORT_STAGE] = copy.deepcopy(dict(report_stage))
    out["stages"] = stages
    out.setdefault("version", MODEL_PROVENANCE_VERSION)
    return out
