"""EVAL-19 (P07 part 1/2): frozen evaluation bundle of one published report.

A later study (EVAL-20) re-asks a forecast question with one input block removed or
changed and measures how far the probability moves. That only means something when
every arm sees exactly the inputs the production report saw, byte for byte. This
module freezes them next to the report, after publication:

``reports/<report_id>/eval_bundle/``
  ``blocks/<name>.txt``  one file per available block (BLOCK_NAMES), nothing else
  ``manifest.json``      ``drf-eval-bundle/v1``: capture (in_pipeline | backfill), ids,
                         created_at, as_of + as_of_source (ledger_commit.resolve_as_of,
                         the rule the ledger row of the same report used),
                         central_question, upstream_models (run.json ``resolved``), run
                         {record_class, run_kind, seed}, publication {markdown_sha256,
                         forecast_sha256 (sealed forecast only)}, per-block {sha256,
                         chars, status ok|unavailable:<reason>[, note]}, targets,
                         bundle_sha256 over the sorted block hashes and the canonical
                         targets, and manifest_sha256 sealing every other field.

:func:`load_bundle` checks the manifest's shape and seal, re-hashes every block file,
rejects any file in ``blocks/`` the manifest does not own, and raises
:class:`BundleIntegrityError` on any difference: a tampered or missing block is never
substituted. Blocks are built deterministically from what the report agent had in
memory (no LLM call); a block that cannot be built is recorded as
``unavailable:<reason>``, never invented.

Capture runs from ``ledger_commit.run_post_publication`` (after the ledger commit)
only under EVAL_BUNDLE_CAPTURE for a publishable report, and never touches the
report's own artifacts. ``backend/scripts/eval_bundle.py`` backfills bundles from
stored handoffs and verifies them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..utils.atomic import write_json_atomic, write_text_atomic
from ..utils.canonical_json import canonical_json_sha256
from ..utils.logger import get_logger

logger = get_logger("mirofish.eval_bundle")

MANIFEST_SCHEMA = "drf-eval-bundle/v1"
BUNDLE_DIRNAME = "eval_bundle"
MANIFEST_NAME = "manifest.json"
BLOCKS_DIRNAME = "blocks"
BLOCK_NAMES = ("brief", "forecast_inputs", "dossier", "quant", "graph", "sim", "market")
STATUS_OK = "ok"
UNAVAILABLE_PREFIX = "unavailable:"
# How a bundle was captured: in the report run (the exact in-memory blocks) or rebuilt
# afterwards from the stored handoff (lower fidelity; see scripts/eval_bundle.py).
CAPTURE_IN_PIPELINE = "in_pipeline"
CAPTURE_BACKFILL = "backfill"
CAPTURE_MODES = (CAPTURE_IN_PIPELINE, CAPTURE_BACKFILL)
# Manifest fields outside the manifest seal: the two hashes themselves.
_UNSEALED_FIELDS = ("bundle_sha256", "manifest_sha256")
DEFAULT_TARGETS = 12
DEFAULT_DOSSIER_CHARS = 16000
GRAPH_FACTS_LIMIT = 20
# report_agent._render_market_pack renders the first 20 market rows (PM-2).
RENDERED_MARKET_ROWS = 20
# run_summary.json simulation_health values whose behaviour data is not usable (REPORT-5).
UNUSABLE_SIM_HEALTH = frozenset({"hollow", "errored", "truncated"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_NUMBER_RE = re.compile(r"^(.*?)(\d+)$")


class BundleIntegrityError(ValueError):
    """A bundle file is missing, unexpected, or no longer matches the manifest."""


def unavailable(reason: str) -> str:
    return f"{UNAVAILABLE_PREFIX}{reason}"


def _is_unavailable(status: Any) -> bool:
    return (isinstance(status, str) and status.startswith(UNAVAILABLE_PREFIX)
            and bool(status[len(UNAVAILABLE_PREFIX):].strip()))


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


def dossier_chars() -> int:
    """EVAL_DOSSIER_CHARS as a positive budget; zero, negative or unreadable values fall
    back to the default, for the in-pipeline capture and the backfill alike."""
    from ..config import Config
    try:
        value = int(getattr(Config, "EVAL_DOSSIER_CHARS", DEFAULT_DOSSIER_CHARS))
    except (TypeError, ValueError):
        return DEFAULT_DOSSIER_CHARS
    return value if value > 0 else DEFAULT_DOSSIER_CHARS


def bundle_sha256(blocks: Mapping[str, Mapping[str, Any]], targets: Sequence[Any]) -> str:
    """sha256 over the sorted (name, block sha256) pairs and the canonical targets."""
    return canonical_json_sha256({
        "blocks": sorted([name, meta.get("sha256")] for name, meta in blocks.items()),
        "targets": list(targets),
    })


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """The manifest seal: canonical sha256 of every field except the two hashes."""
    return canonical_json_sha256({key: value for key, value in manifest.items()
                                  if key not in _UNSEALED_FIELDS})


def _block_path(bundle_dir: str, name: str) -> str:
    return os.path.join(bundle_dir, BLOCKS_DIRNAME, f"{name}.txt")


def _block_files() -> frozenset:
    return frozenset(f"{name}.txt" for name in BLOCK_NAMES)


# ------------------------------------------------------------------ write / load
def write_bundle(bundle_dir: str, *, blocks: Mapping[str, Optional[str]],
                 statuses: Mapping[str, str], targets: Sequence[Dict[str, Any]],
                 meta: Mapping[str, Any], notes: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Write every available block and the manifest; returns the manifest.

    ``blocks[name]`` is the block text or None; ``statuses[name]`` its status ('ok', or
    'unavailable:<reason>' — a None text is never 'ok'). ``meta`` supplies capture
    (CAPTURE_MODES), ids, created_at, as_of, as_of_source, central_question,
    upstream_models, run and publication. Any other file in ``blocks/`` (an earlier
    capture's block that is now unavailable, an interrupted write's temp file) is removed,
    so the directory holds exactly the bundle's own blocks. Raises ValueError for an
    unknown block, an invalid status or capture mode, or a manifest that is not strict
    JSON (NaN, unserialisable values)."""
    unknown = set(blocks) - set(BLOCK_NAMES)
    if unknown:
        raise ValueError(f"unknown bundle block(s): {sorted(unknown)}")
    capture = meta.get("capture")
    if capture not in CAPTURE_MODES:
        raise ValueError(f"capture must be one of {CAPTURE_MODES}, got {capture!r}")
    block_meta: Dict[str, Dict[str, Any]] = {}
    texts: Dict[str, str] = {}
    for name in BLOCK_NAMES:
        text = blocks.get(name)
        status = statuses.get(name) or (STATUS_OK if text else unavailable("not_built"))
        if status != STATUS_OK and not _is_unavailable(status):
            raise ValueError(f"block {name} has invalid status {status!r}")
        if not isinstance(text, str) or not text.strip():
            entry: Dict[str, Any] = {"sha256": None, "chars": 0,
                                     "status": unavailable("empty") if status == STATUS_OK else status}
        else:
            if status != STATUS_OK:
                raise ValueError(f"block {name} has text but status {status!r}")
            texts[name] = text
            entry = {"sha256": _sha256_text(text), "chars": len(text), "status": STATUS_OK}
        if notes and notes.get(name):
            entry["note"] = notes[name]
        block_meta[name] = entry
    manifest: Dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "capture": capture,
        "ids": dict(meta.get("ids") or {}),
        "created_at": meta.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "as_of": meta.get("as_of"),
        "as_of_source": meta.get("as_of_source"),
        "central_question": meta.get("central_question"),
        "upstream_models": meta.get("upstream_models"),
        "run": dict(meta.get("run") or {}),
        "publication": dict(meta.get("publication") or {}),
        "blocks": block_meta,
        "targets": [dict(t) for t in targets],
    }
    # Seal exactly what load_bundle will read back (tuples → lists, strict JSON only).
    manifest = json.loads(json.dumps(manifest, ensure_ascii=False, allow_nan=False))
    manifest["bundle_sha256"] = bundle_sha256(manifest["blocks"], manifest["targets"])
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    blocks_dir = os.path.join(bundle_dir, BLOCKS_DIRNAME)
    if os.path.isdir(blocks_dir):
        keep = {f"{name}.txt" for name in texts}
        for entry_name in os.listdir(blocks_dir):
            path = os.path.join(blocks_dir, entry_name)
            if entry_name not in keep and os.path.isfile(path):
                os.remove(path)
    for name, text in texts.items():
        write_text_atomic(_block_path(bundle_dir, name), text)
    write_json_atomic(os.path.join(bundle_dir, MANIFEST_NAME), manifest)
    return manifest


def _check_block_entry(name: str, entry: Any) -> None:
    """Shape of one manifest block entry: 'ok' with a sha256 and a positive length, or
    'unavailable:<reason>' with neither."""
    if not isinstance(entry, dict):
        raise BundleIntegrityError(f"block {name} entry is not an object")
    status = entry.get("status")
    if status == STATUS_OK:
        sha, chars = entry.get("sha256"), entry.get("chars")
        if (not isinstance(sha, str) or not _SHA256_RE.match(sha)
                or isinstance(chars, bool) or not isinstance(chars, int) or chars <= 0):
            raise BundleIntegrityError(f"block {name} is 'ok' but its sha256/chars are malformed")
    elif _is_unavailable(status):
        if entry.get("sha256") is not None or entry.get("chars") != 0 or isinstance(entry.get("chars"), bool):
            raise BundleIntegrityError(f"block {name} is {status!r} but records content")
    else:
        raise BundleIntegrityError(f"block {name} has invalid status {status!r}")


def _check_block_dir(bundle_dir: str) -> None:
    """``blocks/`` holds nothing but files named after BLOCK_NAMES (absent is fine)."""
    blocks_dir = os.path.join(bundle_dir, BLOCKS_DIRNAME)
    try:
        entries = os.listdir(blocks_dir)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BundleIntegrityError(f"{BLOCKS_DIRNAME}/ unreadable: {exc}") from exc
    extra = sorted(set(entries) - _block_files())
    if extra:
        raise BundleIntegrityError(f"unexpected file(s) in {BLOCKS_DIRNAME}/: {extra}")


def load_bundle(bundle_dir: str) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """``(manifest, {block: text or None})`` after re-hashing every file.

    Raises BundleIntegrityError (and nothing else) when the manifest is unreadable, of
    another schema or malformed (a block entry that is not an object, a status other
    than 'ok' / 'unavailable:<reason>', an unavailable block that records a hash or a
    length, targets that are not a list, a value that is not strict JSON), when its
    manifest_sha256 seal no longer matches (any edited field: as_of, question, ids,
    publication, notes, statuses, ...), when ``blocks/`` holds an unexpected file, an
    'ok' block's file is missing or its sha256/length differs, an unavailable block
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
    for name in BLOCK_NAMES:
        _check_block_entry(name, block_meta[name])
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise BundleIntegrityError("manifest targets are not a list")
    try:
        seal = manifest_sha256(manifest)
        expected_bundle = bundle_sha256(block_meta, targets)
    except (TypeError, ValueError) as exc:
        raise BundleIntegrityError(f"manifest is not canonical JSON: {exc}") from exc
    if manifest.get("manifest_sha256") != seal:
        raise BundleIntegrityError("manifest_sha256 mismatch")
    _check_block_dir(bundle_dir)
    texts: Dict[str, Optional[str]] = {}
    for name in BLOCK_NAMES:
        entry = block_meta[name]
        file_path = _block_path(bundle_dir, name)
        if entry["status"] == STATUS_OK:
            try:
                with open(file_path, "rb") as f:
                    raw = f.read()
            except OSError as exc:
                raise BundleIntegrityError(f"block {name} missing") from exc
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise BundleIntegrityError(f"block {name} sha256 mismatch")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BundleIntegrityError(f"block {name} is not UTF-8") from exc
            if len(text) != entry["chars"]:
                raise BundleIntegrityError(f"block {name} length mismatch")
            texts[name] = text
        else:
            if os.path.lexists(file_path):
                raise BundleIntegrityError(f"block {name} is {entry['status']!r} but has a file")
            texts[name] = None
    if manifest.get("bundle_sha256") != expected_bundle:
        raise BundleIntegrityError("bundle_sha256 mismatch")
    return manifest, texts


# ------------------------------------------------------------------ targets
def _exact_anchor(row: Mapping[str, Any]) -> bool:
    anchor = row.get("market_anchor")
    return (isinstance(anchor, dict)
            and str(anchor.get("resolution_equivalence") or "").strip().lower() == "exact")


def _target_sort_key(row: Mapping[str, Any]) -> Tuple[bool, str, int, str]:
    """'exact'-anchored first, then natural id order (F2 before F10), then the raw id."""
    raw = str(row.get("id")).strip()
    match = _ID_NUMBER_RE.match(raw)
    if match:
        return (not _exact_anchor(row), match.group(1), int(match.group(2)), raw)
    return (not _exact_anchor(row), raw, -1, raw)


def select_targets(forecast: Any, k: int = DEFAULT_TARGETS) -> List[Dict[str, Any]]:
    """Up to ``k`` binaries as study targets, deterministic: those anchored to an
    'exact' market first (case-insensitive, as forecast_extractor compares it), then by
    natural id order. ``pre_market_probability`` is the probability before a
    market-influenced revision (market_influence.prior_probability)."""
    from .forecast_ledger import binary_resolution_date
    rows = [b for b in (forecast.get("binary_forecasts") or [] if isinstance(forecast, dict) else [])
            if isinstance(b, dict) and b.get("id") is not None]
    targets: List[Dict[str, Any]] = []
    for row in sorted(rows, key=_target_sort_key)[:max(0, int(k))]:
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


def research_blocks(actors: Any, research_report: Any, dossier_budget: int
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
        "dossier": _block(lambda: slice_head_tail(report, int(dossier_budget)), "no_research_report")
        if report.strip() else (None, unavailable("no_research_report")),
    }


def research_market_block(snapshot: Any, *, fallback_as_of: Optional[str] = None
                          ) -> Tuple[Optional[str], str]:
    """Backfill market block: the research snapshot (handoff prediction_markets.json) as
    the report loader reads it (the first PREDICTION_MARKETS_MAX rows stamped with the
    snapshot's as_of, the first RENDERED_MARKET_ROWS rendered). The TIME-3 end-date gate
    is evaluated at the snapshot time, never at the wall clock, so a re-backfill renders
    the same bytes: the payload's ``as_of``, else the end of the ``fallback_as_of`` day
    (both parsed by prediction_markets.parse_market_end). No usable time →
    ``unavailable:no_snapshot_time``."""
    from ..config import Config
    from ..utils.prediction_markets import parse_market_end, render_markets_block, stamp_snapshot_as_of
    markets = snapshot.get("markets") if isinstance(snapshot, dict) else snapshot
    rows = [m for m in markets if isinstance(m, dict)] if isinstance(markets, list) else []
    if not rows:
        return None, unavailable("no_research_snapshot")
    snapshot_as_of = snapshot.get("as_of") if isinstance(snapshot, dict) else None
    pinned = parse_market_end(snapshot_as_of) or parse_market_end(fallback_as_of)
    if pinned is None:
        return None, unavailable("no_snapshot_time")
    try:
        max_rows = int(getattr(Config, "PREDICTION_MARKETS_MAX", 20) or 20)
    except (TypeError, ValueError):
        max_rows = 20
    rows = stamp_snapshot_as_of(rows[:max_rows], snapshot_as_of)
    return _block(lambda: render_markets_block(rows[:RENDERED_MARKET_ROWS], now=pinned),
                  "no_research_snapshot")


def publication_hashes(report_dir: str, *, forecast_sealed: bool) -> Dict[str, Optional[str]]:
    """sha256 of the published Markdown, and of forecast.json only when the caller loaded
    it through the final-audit seal (an unsealed sidecar is not part of the publication)."""
    return {"markdown_sha256": _sha256_file(os.path.join(report_dir, "full_report.md")),
            "forecast_sha256": (_sha256_file(os.path.join(report_dir, "forecast.json"))
                                if forecast_sealed else None)}


def upstream_models(pipeline_id: Optional[str]) -> Optional[Dict[str, Any]]:
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
                       now: Optional[datetime] = None,
                       context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Freeze the in-pipeline blocks of a just-published report into
    ``report_dir/eval_bundle``. Reads the agent's in-memory state with getattr and
    degrades per block (``unavailable:<reason>``); makes no LLM call.

    ``context`` is the report's enriched ledger context (``ledger_commit``; default the
    agent's raw ``ledger_context``). ``as_of`` is resolved exactly as the ledger row's
    (``ledger_commit.resolve_as_of``); the graph block is queried at that date only when
    it is a validated or strict actors date, never at the commit-date fallback.
    ``forecast`` is the sealed forecast (None when not sealed: no targets)."""
    from .ledger_commit import resolve_as_of
    moment = now or datetime.now(timezone.utc)
    if context is None:
        raw_context = getattr(agent, "ledger_context", None)
        context = raw_context if isinstance(raw_context, Mapping) else {}
    actors = getattr(agent, "actors", None)
    built = research_blocks(actors, getattr(agent, "research_report", None), dossier_chars())

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

    as_of, as_of_source = resolve_as_of(context, actors, moment)
    question = getattr(agent, "simulation_requirement", None)
    graph_id = getattr(agent, "graph_id", None)
    zep = getattr(agent, "zep_tools", None)
    notes: Dict[str, str] = {}
    if not (graph_id and zep is not None and question):
        built["graph"] = (None, unavailable("no_graph_context"))
    elif as_of_source == "commit_date":
        # No validated anchor and no strict actors date: a commit-date cut is not the
        # research's point in time, so no graph facts are frozen (no look-ahead).
        built["graph"] = (None, unavailable("no_validated_as_of"))
    else:
        degraded: List[bool] = []

        def _graph() -> str:
            result = zep.as_of_search(graph_id, str(question), as_of, limit=GRAPH_FACTS_LIMIT)
            degraded.append(bool(getattr(result, "degraded", False)))
            return "\n".join(str(fact) for fact in (getattr(result, "facts", None) or []))
        built["graph"] = _block(_graph, "no_graph_facts")
        if built["graph"][1] == STATUS_OK and any(degraded):
            notes["graph"] = "degraded_search"   # keyword fallback after a semantic-search failure

    pipeline_id = context.get("pipeline_id")
    meta = {
        "capture": CAPTURE_IN_PIPELINE,
        "ids": {"pipeline": pipeline_id, "report": report_id,
                "simulation": getattr(agent, "simulation_id", None), "graph": graph_id},
        "created_at": moment.isoformat(),
        "as_of": as_of,
        "as_of_source": as_of_source,
        "central_question": question,
        "upstream_models": upstream_models(pipeline_id),
        "run": {"record_class": context.get("record_class"), "run_kind": context.get("run_kind"),
                "seed": context.get("seed")},
        "publication": publication_hashes(report_dir, forecast_sealed=isinstance(forecast, dict)),
    }
    return write_bundle(bundle_dir_for(report_dir),
                        blocks={name: built[name][0] for name in BLOCK_NAMES},
                        statuses={name: built[name][1] for name in BLOCK_NAMES},
                        targets=select_targets(forecast), meta=meta, notes=notes)
