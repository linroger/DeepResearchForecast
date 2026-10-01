"""EVAL-19 (P07 part 1/2): frozen evaluation bundle of one published report.

A later study (EVAL-20) re-asks a forecast question with one input block removed or
changed and measures how far the probability moves. That only means something when
every arm sees exactly the inputs the production report saw, byte for byte. This
module freezes them next to the report, after publication:

``reports/<report_id>/eval_bundle/``
  ``blocks/<name>.txt``  one file per available block (BLOCK_NAMES)
  ``manifest.json``      ``drf-eval-bundle/v1``: ids, created_at, as_of,
                         central_question, upstream_models (run.json ``resolved``),
                         publication {markdown_sha256, forecast_sha256}, per-block
                         {sha256, chars, status ok|unavailable:<reason>[, note]},
                         targets, and bundle_sha256 over the sorted block hashes and
                         the canonical targets.

:func:`load_bundle` re-hashes every file and raises :class:`BundleIntegrityError` on
any difference: a tampered or missing block is never substituted. Blocks are built
deterministically from what the report agent had in memory (no LLM call); a block
that cannot be built is recorded as ``unavailable:<reason>``, never invented.

Capture runs from ``ledger_commit.run_post_publication`` (after the ledger commit)
only under EVAL_BUNDLE_CAPTURE for a publishable report, and never touches the
report's own artifacts. ``backend/scripts/eval_bundle.py`` backfills bundles from
stored handoffs and verifies them.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..utils.atomic import write_json_atomic, write_text_atomic
from ..utils.canonical_json import canonical_json_sha256
from ..utils.logger import get_logger

logger = get_logger("mirofish.eval_bundle")

MANIFEST_SCHEMA = "drf-eval-bundle/v1"
BUNDLE_DIRNAME = "eval_bundle"
MANIFEST_NAME = "manifest.json"
BLOCK_NAMES = ("brief", "forecast_inputs", "dossier", "quant", "graph", "sim", "market")
STATUS_OK = "ok"
DEFAULT_TARGETS = 12
DEFAULT_DOSSIER_CHARS = 16000
GRAPH_FACTS_LIMIT = 20
# run_summary.json simulation_health values whose behaviour data is not usable (REPORT-5).
UNUSABLE_SIM_HEALTH = frozenset({"hollow", "errored", "truncated"})


class BundleIntegrityError(ValueError):
    """A bundle file is missing or its bytes no longer match the manifest."""


def unavailable(reason: str) -> str:
    return f"unavailable:{reason}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def bundle_dir_for(report_dir: str) -> str:
    return os.path.join(report_dir, BUNDLE_DIRNAME)


def bundle_sha256(blocks: Mapping[str, Mapping[str, Any]], targets: Sequence[Any]) -> str:
    """sha256 over the sorted (name, block sha256) pairs and the canonical targets."""
    return canonical_json_sha256({
        "blocks": sorted([name, (meta or {}).get("sha256")] for name, meta in blocks.items()),
        "targets": list(targets),
    })


# ------------------------------------------------------------------ write / load
def write_bundle(bundle_dir: str, *, blocks: Mapping[str, Optional[str]],
                 statuses: Mapping[str, str], targets: Sequence[Dict[str, Any]],
                 meta: Mapping[str, Any], notes: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Write every available block and the manifest; returns the manifest.

    ``blocks[name]`` is the block text or None; ``statuses[name]`` its status ('ok', or
    'unavailable:<reason>' — a None text is never 'ok'). ``meta`` supplies ids,
    created_at, as_of, central_question, upstream_models and publication."""
    unknown = set(blocks) - set(BLOCK_NAMES)
    if unknown:
        raise ValueError(f"unknown bundle block(s): {sorted(unknown)}")
    block_meta: Dict[str, Dict[str, Any]] = {}
    for name in BLOCK_NAMES:
        text = blocks.get(name)
        status = statuses.get(name) or (STATUS_OK if text else unavailable("not_built"))
        block_path = os.path.join(bundle_dir, "blocks", f"{name}.txt")
        if not isinstance(text, str) or not text.strip():
            if status == STATUS_OK:
                status = unavailable("empty")
            if os.path.exists(block_path):
                os.remove(block_path)   # a re-capture never leaves an earlier capture's block
            entry: Dict[str, Any] = {"sha256": None, "chars": 0, "status": status}
        else:
            if status != STATUS_OK:
                raise ValueError(f"block {name} has text but status {status!r}")
            write_text_atomic(block_path, text)
            entry = {"sha256": _sha256_text(text), "chars": len(text), "status": STATUS_OK}
        if notes and notes.get(name):
            entry["note"] = notes[name]
        block_meta[name] = entry
    manifest: Dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "ids": dict(meta.get("ids") or {}),
        "created_at": meta.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "as_of": meta.get("as_of"),
        "central_question": meta.get("central_question"),
        "upstream_models": meta.get("upstream_models"),
        "publication": dict(meta.get("publication") or {}),
        "blocks": block_meta,
        "targets": [dict(t) for t in targets],
    }
    manifest["bundle_sha256"] = bundle_sha256(block_meta, manifest["targets"])
    write_json_atomic(os.path.join(bundle_dir, MANIFEST_NAME), manifest)
    return manifest


def load_bundle(bundle_dir: str) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """``(manifest, {block: text or None})`` after re-hashing every file.

    Raises BundleIntegrityError when the manifest is unreadable or of another schema,
    an 'ok' block's file is missing or its sha256/length differs, an unavailable block
    has a file, or the bundle_sha256 no longer matches."""
    path = os.path.join(bundle_dir, MANIFEST_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as exc:
        raise BundleIntegrityError(f"manifest unreadable: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise BundleIntegrityError("manifest is not a drf-eval-bundle/v1 manifest")
    block_meta = manifest.get("blocks")
    if not isinstance(block_meta, dict) or set(block_meta) != set(BLOCK_NAMES):
        raise BundleIntegrityError("manifest blocks do not match BLOCK_NAMES")
    texts: Dict[str, Optional[str]] = {}
    for name in BLOCK_NAMES:
        entry = block_meta[name] if isinstance(block_meta[name], dict) else {}
        file_path = os.path.join(bundle_dir, "blocks", f"{name}.txt")
        if entry.get("status") == STATUS_OK:
            try:
                with open(file_path, "rb") as f:
                    raw = f.read()
            except OSError as exc:
                raise BundleIntegrityError(f"block {name} missing") from exc
            if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
                raise BundleIntegrityError(f"block {name} sha256 mismatch")
            text = raw.decode("utf-8")
            if len(text) != entry.get("chars"):
                raise BundleIntegrityError(f"block {name} length mismatch")
            texts[name] = text
        else:
            if os.path.exists(file_path):
                raise BundleIntegrityError(f"block {name} is {entry.get('status')!r} but has a file")
            texts[name] = None
    if manifest.get("bundle_sha256") != bundle_sha256(block_meta, manifest.get("targets") or []):
        raise BundleIntegrityError("bundle_sha256 mismatch")
    return manifest, texts


# ------------------------------------------------------------------ targets
def select_targets(forecast: Any, k: int = DEFAULT_TARGETS) -> List[Dict[str, Any]]:
    """Up to ``k`` binaries as study targets, deterministic: those anchored to an
    'exact' market first, then by id. ``pre_market_probability`` is the probability
    before a market-influenced revision (market_influence.prior_probability)."""
    from .forecast_ledger import binary_resolution_date
    rows = [b for b in (forecast.get("binary_forecasts") or [] if isinstance(forecast, dict) else [])
            if isinstance(b, dict) and b.get("id") is not None]

    def exact(row: Dict[str, Any]) -> bool:
        anchor = row.get("market_anchor")
        return isinstance(anchor, dict) and str(anchor.get("resolution_equivalence") or "") == "exact"

    ordered = sorted(rows, key=lambda r: (not exact(r), str(r.get("id"))))
    targets: List[Dict[str, Any]] = []
    for row in ordered[:max(0, int(k))]:
        influence = row.get("market_influence")
        prior = influence.get("prior_probability") if isinstance(influence, dict) else None
        anchor = row.get("market_anchor") if isinstance(row.get("market_anchor"), dict) else None
        targets.append({
            "target_id": str(row.get("id")),
            "statement": row.get("statement"),
            "resolution_criteria": row.get("resolution_criteria"),
            "resolution_date": binary_resolution_date(row),
            "published_probability": row.get("probability"),
            "pre_market_probability": prior if prior is not None else row.get("probability"),
            "market_anchor": ({"market_id": anchor.get("market_id"),
                               "equivalence": anchor.get("resolution_equivalence"),
                               "price_at_research": anchor.get("price_at_research")}
                              if anchor else None),
        })
    return targets


# ------------------------------------------------------------------ blocks
def _block(builder: Callable[[], Any], reason: str) -> Tuple[Optional[str], str]:
    """Run one deterministic block builder; an empty result or an error is unavailable."""
    try:
        text = builder()
    except Exception as exc:  # noqa: BLE001 — one block never breaks the bundle
        logger.warning(f"eval bundle: block {reason} failed ({type(exc).__name__}: {exc})")
        return None, unavailable(f"error:{type(exc).__name__}")
    if not isinstance(text, str) or not text.strip():
        return None, unavailable(reason)
    return text, STATUS_OK


def research_blocks(actors: Any, research_report: Any, dossier_chars: int
                    ) -> Dict[str, Tuple[Optional[str], str]]:
    """brief / forecast_inputs / quant (utils.actors renderers) and dossier
    (forecast_extractor.slice_head_tail), each ``(text, status)``."""
    from ..utils import actors as actor_utils
    from .forecast_extractor import slice_head_tail
    actors_ok = isinstance(actors, dict) and bool(actors)
    report = research_report if isinstance(research_report, str) else ""
    return {
        "brief": _block(lambda: actor_utils.situation_brief(actors), "no_actors")
        if actors_ok else (None, unavailable("no_actors")),
        "forecast_inputs": _block(lambda: actor_utils.forecast_inputs_block(actors), "no_forecast_inputs")
        if actors_ok else (None, unavailable("no_actors")),
        "quant": _block(lambda: actor_utils.quantitative_facts_block(actors), "no_quantitative_facts")
        if actors_ok else (None, unavailable("no_actors")),
        "dossier": _block(lambda: slice_head_tail(report, int(dossier_chars)), "no_research_report")
        if report.strip() else (None, unavailable("no_research_report")),
    }


def _publication(report_dir: str) -> Dict[str, Optional[str]]:
    return {"markdown_sha256": _sha256_file(os.path.join(report_dir, "full_report.md")),
            "forecast_sha256": _sha256_file(os.path.join(report_dir, "forecast.json"))}


def _upstream_models(pipeline_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """run.json ``resolved`` of the owning pipeline, or None."""
    if not pipeline_id:
        return None
    try:
        from .pipeline_orchestrator import PipelineManager
        with open(PipelineManager.manifest_path(pipeline_id), encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:  # noqa: BLE001 — provenance only
        return None
    resolved = manifest.get("resolved") if isinstance(manifest, dict) else None
    return resolved if isinstance(resolved, dict) else None


def capture_from_agent(agent: Any, report_id: str, *, report_dir: str, forecast: Any,
                       now: Optional[datetime] = None) -> Dict[str, Any]:
    """Freeze the in-pipeline blocks of a just-published report into
    ``report_dir/eval_bundle``. Reads the agent's in-memory state with getattr and
    degrades per block (``unavailable:<reason>``); makes no LLM call."""
    from ..config import Config
    dossier_chars = int(getattr(Config, "EVAL_DOSSIER_CHARS", DEFAULT_DOSSIER_CHARS) or DEFAULT_DOSSIER_CHARS)
    actors = getattr(agent, "actors", None)
    built = research_blocks(actors, getattr(agent, "research_report", None), dossier_chars)

    market = getattr(agent, "_market_pack", None)
    built["market"] = ((market, STATUS_OK) if isinstance(market, str) and market.strip()
                       else (None, unavailable("no_market_pack")))

    health = None
    health_fn = getattr(agent, "_run_summary_health", None)
    if callable(health_fn):
        try:
            health = health_fn()[0]
        except Exception:  # noqa: BLE001
            health = None
    if health in UNUSABLE_SIM_HEALTH:
        built["sim"] = (None, unavailable(health))
    else:
        pack = getattr(agent, "_signal_pack", None)
        if not (isinstance(pack, str) and pack.strip()) and callable(getattr(agent, "_build_signal_pack", None)):
            built["sim"] = _block(agent._build_signal_pack, "no_signal_pack")
        else:
            built["sim"] = ((pack, STATUS_OK) if isinstance(pack, str) and pack.strip()
                            else (None, unavailable("no_signal_pack")))

    context = getattr(agent, "ledger_context", None)
    context = context if isinstance(context, Mapping) else {}
    as_of = context.get("as_of_date") or (actors.get("as_of_date") if isinstance(actors, dict) else None)
    question = getattr(agent, "simulation_requirement", None)
    graph_id = getattr(agent, "graph_id", None)
    zep = getattr(agent, "zep_tools", None)
    if graph_id and zep is not None and question and as_of:
        def _graph() -> str:
            result = zep.as_of_search(graph_id, str(question)[:350], as_of, limit=GRAPH_FACTS_LIMIT)
            return "\n".join(str(fact) for fact in (getattr(result, "facts", None) or []))
        built["graph"] = _block(_graph, "no_graph_facts")
    else:
        built["graph"] = (None, unavailable("no_graph_context"))

    pipeline_id = context.get("pipeline_id")
    meta = {
        "ids": {"pipeline": pipeline_id, "report": report_id,
                "simulation": getattr(agent, "simulation_id", None), "graph": graph_id},
        "created_at": (now or datetime.now(timezone.utc)).isoformat(),
        "as_of": as_of,
        "central_question": question,
        "upstream_models": _upstream_models(pipeline_id),
        "publication": _publication(report_dir),
    }
    return write_bundle(bundle_dir_for(report_dir),
                        blocks={name: built[name][0] for name in BLOCK_NAMES},
                        statuses={name: built[name][1] for name in BLOCK_NAMES},
                        targets=select_targets(forecast), meta=meta)
