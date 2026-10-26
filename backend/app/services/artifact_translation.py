"""Validated, source-bound display translations; canonical artifacts stay untouched.

Native overlays retain legacy keys. Visible-text requests are separately cached by
simulation/language/context and inventory digest, so actor/analyst projections can
never leak through a public/default cache read. GET never acquires or translates.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from .translation_tools import translate_pairs

logger = logging.getLogger("mirofish.translation")
_LANGS = {"zh": "简体中文（Simplified Chinese）", "en": "professional analyst-grade English"}
_SIM_ID_RE = re.compile(r"^sim_[A-Za-z0-9_-]{1,64}$")
_GRAPH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_PAIRS, _MAX_TEXT, _MAX_CHARACTERS = 20000, 24000, 12000000
_PAGE_PAIRS, _PAGE_CHARACTERS = 216, 96000
_OPERATION = "artifact-overlay"
_CACHE_VERSION = 4


def _sha(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _digest(value):
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lang_name(lang):
    if lang not in _LANGS:
        raise ValueError("unsupported language")
    return _LANGS[lang]


def _read_json(path, limit=12000000):
    try:
        if os.path.islink(path) or os.path.getsize(path) > limit:
            return None
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return None


def _load_cache(path):
    # Receipts plus source and target text exceed the source-only input bound.
    data = _read_json(path, limit=128000000)
    return data if isinstance(data, dict) and isinstance(data.get("entries"), dict) else {}


def _save_cache(path, cache):
    from .translation.scheduler import publication_guard
    with publication_guard():
        _write_cache(path, cache)


def _write_cache(path, cache):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    # No fixed .tmp shared between language/context workers.
    fd, tmp = tempfile.mkstemp(prefix=".translation-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _graph_snapshot(graph_id):
    """The complete graph, with deterministic ordering and a full source seal."""
    from .graph_builder import GraphBuilderService
    data = GraphBuilderService(api_key=Config.ZEP_API_KEY).get_graph_data(graph_id, slim=False)
    if not isinstance(data, dict):
        raise FileNotFoundError("unknown graph")
    nodes = sorted(data.get("nodes") or [], key=lambda row: str(row.get("uuid", "")))
    edges = sorted(data.get("edges") or [], key=lambda row: str(row.get("uuid", "")))
    if (data.get("truncated") or data.get("total_node_count", len(nodes)) != len(nodes)
            or data.get("total_edge_count", len(edges)) != len(edges)):
        raise ValueError("graph source returned an incomplete inventory; refresh the source")
    pairs = []
    seen = set()
    for kind, rows, field in (("node", nodes, "summary"), ("edge", edges, "fact")):
        for row in rows:
            source = str(row.get(field) or "").strip()
            if not source:
                continue
            key = f"{kind}:{row.get('uuid')}:{field}"
            if not row.get("uuid") or key in seen:
                raise ValueError("graph translation requires unique stable field identities")
            seen.add(key)
            pairs.append((key, source))
    revision = data.get("revision", data.get("generation_id"))
    fingerprint = _digest({"nodes": nodes, "edges": edges, "revision": revision})
    return pairs, fingerprint, revision


def _graph_pairs(graph_id: str) -> List[Tuple[str, str]]:
    return _graph_snapshot(graph_id)[0]


def _graph_cache_path(graph_id: str, lang: str) -> Optional[str]:
    if not _GRAPH_ID_RE.match(graph_id or ""):
        return None
    # uploads/graph_translations/<id>/<lang>.json（UPLOAD_FOLDER 已指向 <app>/../uploads）
    folder = os.path.join(str(Config.UPLOAD_FOLDER), "graph_translations", graph_id)
    return os.path.join(folder, f"{lang}.json")



def _sim_dir(sim_id):
    if not _SIM_ID_RE.fullmatch(sim_id or ""):
        return None
    root = os.path.realpath(str(Config.OASIS_SIMULATION_DATA_DIR))
    path = os.path.join(root, sim_id)
    if os.path.islink(path) or not os.path.isdir(path) or os.path.realpath(path) != path:
        return None
    return path


# Human-readable leaf fields in actual report/world schemas. Machine contracts,
# quantities, statuses, URLs and arbitrary JSON object keys retain their bytes.
_TEXT_FIELDS = frozenset({
    "question", "central_question", "name", "title", "label", "description", "summary", "text",
    "content", "message", "statement", "rationale", "cause", "headline", "narrative", "brief", "digest",
    "note", "notes", "explanation", "reason", "reasoning", "role", "stance", "memory", "persona", "bio",
    "self_description", "type", "category", "relationship", "terms", "response", "red_line", "event",
    "rules_primary", "rules_secondary", "snippet", "claim", "counterclaim", "pro", "con", "why",
    "resolution_criteria", "settlement_criteria", "condition", "interpretation", "background",
    "current_situation", "key_uncertainties", "critical_drivers", "watchpoints", "subject", "basis_label",
    "caption", "geography", "provider_name", "event_title", "xlabel", "ylabel", "x_label", "y_label", "x_axis_label", "y_axis_label",
})
_TEXT_LISTS = frozenset({
    "goals", "plans", "beliefs", "red_lines", "hot_topics", "key_events", "effects_fired", "actions",
    "scheduled_events", "commitments_lapsed", "arbiter_problems", "key_uncertainties", "critical_drivers",
    "watchpoints", "risks", "constraints", "assumptions", "drivers", "triggers", "limitations",
    "priorityChanges", "issues", "failed_sections", "causal_links", "counterarguments", "indicators",
    "situation_brief", "overview", "details", "parameters", "effects", "transfers", "arguments",
    "charts", "viz_manifest", "datasets", "geography", "geographies", "indicators_to_watch",
})
_KEEP_FIELDS = frozenset({
    "id", "uuid", "unit", "units", "url", "href", "path", "png_path", "status", "schema_version",
    "schemaVersion", "quote_unit", "quote_basis", "probability_basis", "outcome", "source_ref", "source_id",
    "provider", "published_at", "retrieved_at", "captured_at", "as_of", "as_of_date", "horizon_date", "date",
    "engine", "simulation_id", "generation_id", "revision", "language", "source_sha256", "source_lang",
    "target_lang", "valueStatus", "kind", "numeric", "prices", "quote", "citations", "binding", "basis",
    "sourceBindings", "visibility", "provenance", "raw", "raw_source", "evidence_digest", "forecast_effect",
})


# These are structured data, not free prose collections. Walk their explicit
# human-readable descendants without translating factual/code-valued siblings.
_CODED_CONTAINERS = frozenset({
    "datasets", "charts", "viz_manifest", "details", "parameters", "effects", "transfers",
})


def _text_paths(value, prefix="", inherited=False, depth=0):
    if depth > 20:
        return
    if isinstance(value, dict):
        parts = prefix.split("/")
        relation = (len(parts) >= 2 and parts[-2] == "relationships") or (
            "source" in value and "target" in value)
        for key, item in value.items():
            key = str(key)
            pointer = prefix + "/" + key.replace("~", "~0").replace("/", "~1")
            if key in {"source", "target"}:
                # Relationship endpoints are canonical identities, even when
                # they look like prose. Only known data/chart source-credit
                # labels have a human-text source field.
                credit = (not relation and key == "source" and isinstance(item, str)
                          and any(part in {"datasets", "charts", "viz_manifest"} for part in parts))
                if credit:
                    yield from _text_paths(item, pointer, True, depth + 1)
                continue
            if key == "basis" and relation and isinstance(item, str):
                # The dossier renders this scalar explanation. A structured
                # basis object remains canonical, including refs/provenance.
                yield from _text_paths(item, pointer, True, depth + 1)
                continue
            if key in _KEEP_FIELDS or key.endswith(("_id", "Id", "_sha256", "_at", "_path")):
                continue
            prose = (key in _TEXT_FIELDS or key in _TEXT_LISTS or inherited) if key not in _CODED_CONTAINERS else False
            yield from _text_paths(item, pointer, prose, depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _text_paths(item, prefix + "/" + str(index), inherited, depth + 1)
    elif isinstance(value, str) and inherited and value.strip():
        if value in {"seed", "changed", "unchanged"}:
            return
        if not re.fullmatch(r"https?://\S+|[-+]?\d[\d.,% -]*", value.strip()):
            yield prefix, value


def _simulation_projection(sim_id, context):
    # The API's source readers are also the UI's visibility/publication gate.
    # No raw actor state, hidden record, or arbitrary filesystem scan is allowed.
    from ..api.simulation import simulation_translation_projection
    return simulation_translation_projection(sim_id, context)


def _projection_strings(value):
    """Allowed source strings after the resource's visibility projection.

    This is membership checking only, never the default translation inventory.
    Canonical IDs/typed fields are not changed by an overlay; only explicitly
    requested visible prose is sent to the translator.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in {"private_rationale", "raw", "raw_source", "credentials"}:
                yield from _projection_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _projection_strings(item)
    elif isinstance(value, str) and value.strip():
        yield value


def _selected_pairs(texts, projection):
    pairs = _visible_pairs(texts)
    permitted = set(_projection_strings(projection))
    # The UI uses bounded persona snippets. A substring may select public text,
    # but cannot authorize text from any unprojected file or another view.
    for _, source in pairs:
        if source not in permitted and not any(source in text for text in permitted):
            raise ValueError("translation text is not in the permitted visible projection")
    return pairs


def _context(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {
        "engine", "platform", "round", "generation_id", "revision", "view", "actor_id", "surface"}:
        raise ValueError("invalid translation context")
    for _key, item in value.items():
        if (not isinstance(item, (str, int, type(None))) or isinstance(item, bool)
                or len(str(item)) > 256):
            raise ValueError("invalid translation context field")
    return dict(value)


def _visible_pairs(texts):
    if not isinstance(texts, list) or len(texts) > _MAX_PAIRS:
        raise ValueError("texts must be a bounded string list")
    unique = {}
    size = 0
    for text in texts:
        if not isinstance(text, str) or len(text) > _MAX_TEXT:
            raise ValueError("invalid or oversized translation text")
        if text.strip():
            unique[_sha(text)] = text
    for text in unique.values():
        size += len(text)
    if size > _MAX_CHARACTERS:
        raise ValueError("translation text inventory exceeds limit")
    return [("text:" + key, value) for key, value in sorted(unique.items())]


def _model_engine():
    from .model_translation import ENGINE
    return ENGINE


def _translation_context(identity):
    return ("Human-readable " + identity["kind"] +
            " display fields. Canonical structured facts are copied separately. "
            "Source and visibility context: " + _digest(identity["scope"]))


def _entry_valid(entry, source, identity):
    from .model_translation import valid_receipt
    from .translation.contracts import scope_digest
    try:
        receipt = entry.get("receipt") if isinstance(entry, dict) else None
        if isinstance(receipt, dict) and receipt.get("resource_scope_sha256") is not None:
            expected = scope_digest({key: identity[key] for key in
                                    ("kind", "ref_id", "scope", "source_fingerprint")})
            if receipt["resource_scope_sha256"] != expected:
                return False
        return (isinstance(entry, dict) and entry.get("sha") == _sha(source)
                and entry.get("text_sha256") == _sha(entry.get("text"))
                and valid_receipt(source, entry.get("text"), identity["target_lang"],
                    entry.get("receipt"), context=_translation_context(identity)))
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def _identity(kind, ref_id, lang, pairs, context, source_fingerprint=None):
    source_fingerprint = source_fingerprint or _digest(pairs)
    scope = {"context": context, "source_fingerprint": source_fingerprint}
    return {"schema_version": _CACHE_VERSION, "translation_engine": _model_engine(),
            "adapter_version": 2, "kind": kind, "ref_id": ref_id, "scope": scope,
            "target_lang": lang, "context": context,
            "request_digest": _digest([kind, ref_id, lang, context, pairs]) if kind == "simulation"
                else _digest([kind, ref_id, lang, scope, pairs]),
            "source_fingerprint": source_fingerprint}


def _cache_valid(cache, identity):
    return all(cache.get(key) == value for key, value in identity.items())


def _job(cache):
    """Read durable operation state. Store failure cannot hide admitted content."""
    saved = cache.get("translation_job")
    if not isinstance(saved, dict) or not saved.get("job_id"):
        unit = cache.get("unit_job")
        if isinstance(unit, dict) and unit.get("job_state") in {"queued", "running"}:
            # A unit checkpoint alone does not prove a live scheduler owner.
            return {**unit, "job_state": "interrupted", "status": "interrupted"}
        return unit
    try:
        from .translation.scheduler import status
        return status(saved["job_id"]) or {**saved, "job_state": "interrupted", "status": "interrupted"}
    except Exception:
        return {"job_id": saved["job_id"], "job_state": "interrupted", "status": "interrupted",
                "issues": ["Translation coordinator is unavailable; accepted text is retained."]}


def _response(cache, identity, pairs, generating=False, job=None):
    scope_ok = _cache_valid(cache, identity)
    entries = cache.get("entries", {}) if scope_ok else {}
    overlay, translations, failed = {}, [], []
    for key, source in pairs:
        entry = entries.get(key)
        if _entry_valid(entry, source, identity):
            overlay[key] = entry["text"]
            translations.append({"source": source, "text": entry["text"], "source_sha256": _sha(source), "key": key})
        else:
            failed.append(key)
    pending = len(failed)
    active_keys = {key for key, _ in pairs}
    refresh_keys = cache.get("refresh_pending_keys", []) if scope_ok else []
    refresh_pending = len(set(refresh_keys) & active_keys)
    incomplete = bool(pending or refresh_pending)
    job = job or (_job(cache) if scope_ok else None)
    state = (job or {}).get("job_state", (job or {}).get("status"))
    generating = generating or state in {"queued", "running", "waiting_provider", "generating"}
    status = ("generating" if generating else "empty" if not pairs else "available" if not incomplete
              else "partial" if overlay else "failed" if scope_ok and cache.get("attempted") else "unavailable")
    if incomplete and state in {"interrupted", "cancelled"}:
        status = state
    issues = list(cache.get("issues") or []) if scope_ok else []
    if incomplete and not issues:
        issues = ["Some source text remains untranslated; resume pending entries." if pending else
                  "A refresh is incomplete; previous validated translations are retained."]
    continuation = bool(incomplete and not generating and scope_ok and cache.get("page_complete")
                        and state not in {"failed", "interrupted", "cancelled"})
    return {**identity, "simulation_id": identity["ref_id"] if identity["kind"] == "simulation" else None,
            "status": status, "overlay": overlay, "translations": translations,
            "translated": len(overlay), "total_candidates": len(pairs), "pending": pending,
            "cached": len(overlay), "partial": incomplete, "retryable": bool(incomplete and not generating),
            "refresh_pending": refresh_pending, "translation_job": job,
            "continuation": {"available": continuation, "page_size": _PAGE_PAIRS,
                             "cursor": str(cache.get("page_index", -1) + 1) if continuation else None},
            "coverage": {"required": len(pairs), "accepted": len(overlay), "pending": pending,
                         "complete": not incomplete, "page_size": _PAGE_PAIRS},
            "failed_keys": failed, "issues": issues if incomplete else [],
            "call_failures": cache.get("call_failures", 0) if scope_ok else 0,
            "model_calls": cache.get("model_calls", 0) if scope_ok else 0,
            "updated_at": cache.get("updated_at") if scope_ok else None}


def _check_inventory(pairs):
    if (len(pairs) > _MAX_PAIRS or sum(len(text) for _, text in pairs) > _MAX_CHARACTERS
            or any(len(text) > _MAX_TEXT for _, text in pairs)):
        raise ValueError("translation inventory exceeds explicit supported bounds; narrow the visible selection")


def _inventory(kind, ref_id, lang, texts=None, context=None, request_digest=None):
    _lang_name(lang)
    context = _context(context)
    if kind == "graph":
        base = _graph_cache_path(ref_id, lang)
        if not base:
            raise ValueError("invalid graph id")
        pairs, fingerprint, revision = _graph_snapshot(ref_id)
        if context.get("revision") not in (None, "", revision):
            raise ValueError("graph revision changed; refresh the graph")
        context = {"revision": revision} if revision is not None else {}
        identity = _identity(kind, ref_id, lang, pairs, context, fingerprint)
        if request_digest and request_digest != identity["request_digest"]:
            raise ValueError("graph source changed; refresh the graph")
        path = os.path.join(os.path.dirname(base), lang, identity["request_digest"] + ".json")
    elif kind == "simulation":
        folder = _sim_dir(ref_id)
        if not folder:
            raise FileNotFoundError("unknown simulation")
        if request_digest is not None:
            if not _DIGEST_RE.fullmatch(request_digest):
                raise ValueError("invalid request digest")
            manifest = os.path.join(folder, "translations", lang, request_digest + ".json")
            cache = _load_cache(manifest)
            if not cache:
                raise FileNotFoundError("translation selection has not been requested")
            if cache.get("context") != context or cache.get("ref_id") != ref_id:
                raise ValueError("translation request context does not match")
            texts = (None if cache.get("mode") == "native" else
                     [value for _, value in cache.get("pairs", [])])
        projection = _simulation_projection(ref_id, context)
        # Native fallback covers only this visible projection. Completed records
        # require the explicit record surface and never enter a default scan.
        pairs = (_selected_pairs(texts, projection) if texts is not None else
                 [("path:visible" + key, value) for key, value in _text_paths(projection)])
        identity = _identity(kind, ref_id, lang, pairs, context, _digest(projection))
        if request_digest and identity["request_digest"] != request_digest:
            raise ValueError("translation source or request context does not match")
        path = os.path.join(folder, "translations", lang,
                            identity["request_digest"] + "." + identity["source_fingerprint"] + ".json")
    else:
        raise ValueError("unsupported translation kind")
    _check_inventory(pairs)
    return path, identity, pairs


def _pages(pairs):
    """Stable bounded pages over the *whole* frozen inventory, never a cutoff."""
    page, size = [], 0
    for pair in pairs:
        if page and (len(page) >= _PAGE_PAIRS or size + len(pair[1]) > _PAGE_CHARACTERS):
            yield page
            page, size = [], 0
        page.append(pair)
        size += len(pair[1])
    if page:
        yield page


def _cache_lock(path):
    import contextlib
    import fcntl
    @contextlib.contextmanager
    def locked():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".lock", "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return locked()


def _translate_inventory(path, identity, pairs, force=False):
    _save_selection(path, identity, pairs)
    with _cache_lock(path):
        return _translate_inventory_locked(path, identity, pairs, force)


def _save_selection(path, identity, pairs):
    if identity["kind"] == "simulation":
        # Immutable selection manifest is separate from each source generation's
        # output. It lets a reloaded browser discover a job by its visible texts.
        manifest = os.path.join(os.path.dirname(path), identity["request_digest"] + ".json")
        if not os.path.isfile(manifest):
            _save_cache(manifest, {"ref_id": identity["ref_id"], "context": identity["context"],
                                   "pairs": pairs, "entries": {},
                                   "mode": "visible" if all(key.startswith("text:") for key, _ in pairs) else "native"})


def _pool_identity(identity):
    return {key: identity[key] for key in
            ("schema_version", "adapter_version", "translation_engine", "kind", "ref_id", "target_lang", "scope")}


def _translate_inventory_locked(path, identity, pairs, force=False):
    cache = _load_cache(path)
    if not _cache_valid(cache, identity):
        cache = {**identity, "entries": {}, "pairs": pairs}
    # Reuse across selections only within the very same source/visibility seal.
    # The old language-wide pool could mix analyst/public and changed contexts.
    pool_identity = _pool_identity(identity)
    pool_path = os.path.join(os.path.dirname(path), ".validated-v2-" + _digest(pool_identity) + ".json")
    pool = _load_cache(pool_path)
    if not force and _cache_valid(pool, pool_identity):
        for key, source in pairs:
            entry = pool["entries"].get(_sha(source))
            if _entry_valid(entry, source, identity):
                cache["entries"].setdefault(key, entry)
    before = _response(cache, identity, pairs)
    missing = set(before["failed_keys"])
    refresh = set(cache.get("refresh_pending_keys") or [])
    if force and not missing and not refresh:
        refresh = {key for key, _ in pairs}
        cache["refresh_generation"] = int(cache.get("refresh_generation", 0)) + 1
        cache["refresh_entries"] = {}
    cache["refresh_pending_keys"] = sorted(refresh)
    pending = missing | refresh
    if not pending:
        if cache.get("entries"):
            _save_cache(path, cache)
        return before
    cache.update(attempted=True, pairs=pairs, updated_at=_now(), issues=[], page_complete=False)
    _save_cache(path, cache)
    # One invocation advances a single bounded page. Retrying uses the same
    # page identity until accepted, then moves to the next page without replay.
    index, page = next((index, page) for index, page in enumerate(_pages(pairs))
                       if any(key in pending for key, _ in page))
    cache["page_index"] = index
    refresh_page = bool(refresh & {key for key, _ in page})
    refreshing = bool(refresh)
    admitted_entries = cache.get("refresh_entries", {}) if refreshing else cache["entries"]
    seed = {key: {"source": source, "target": admitted_entries[key]["text"],
                  "receipt": admitted_entries[key]["receipt"]}
            for key, source in page if key not in refresh and _entry_valid(admitted_entries.get(key), source, identity)}
    durable_identity = {"kind": identity["kind"], "ref_id": identity["ref_id"],
        "scope": identity["scope"], "source_fingerprint": identity["source_fingerprint"],
        "request_digest": identity["request_digest"], "page": index,
        "refresh_generation": cache.get("refresh_generation", 0) if refresh_page else 0}
    if any(not value["receipt"].get("resource_scope_sha256") for value in seed.values()):
        # This adapter has already checked the full cache source/visibility seal
        # and exact receipt. Only its admitted legacy entries get this capability;
        # a receipt explicitly bound to another scope was rejected above.
        from .translation.contracts import trusted_import
        seed = trusted_import(seed, durable_identity)
    failures = 0
    def failed():
        nonlocal failures
        failures += 1
    def progress(mapping):
        receipts = getattr(mapping, "receipts", {})
        publication_changed = not refreshing
        for key, source in page:
            if key not in mapping:
                continue
            entry = {"sha": _sha(source), "text": mapping[key], "text_sha256": _sha(mapping[key]),
                     "receipt": receipts.get(key)}
            if _entry_valid(entry, source, identity):
                if refreshing:
                    cache.setdefault("refresh_entries", {})[key] = entry
                else:
                    cache["entries"][key] = entry
                refresh.discard(key)
        if refreshing and not refresh:
            # A replacement activates as one map. Until this point every GET
            # keeps the complete prior generation, even after partial success.
            cache["entries"].update(cache.get("refresh_entries", {}))
            cache["refresh_entries"] = {}
            cache["published_generation"] = cache.get("refresh_generation", 0)
            publication_changed = True
        cache["refresh_pending_keys"] = sorted(refresh)
        cache.update(updated_at=_now(), call_failures=failures,
                     model_calls=getattr(mapping, "calls_used", 0),
                     review_issues=dict(getattr(mapping, "issues", {})))
        if getattr(mapping, "job", None):
            cache["unit_job"] = mapping.job
        _save_cache(path, cache)
        if not publication_changed:
            return
        with _cache_lock(pool_path):
            stored = _load_cache(pool_path)
            pooled = stored["entries"] if _cache_valid(stored, pool_identity) else {}
            for key, source in pairs if refreshing else page:
                entry = cache["entries"].get(key)
                if _entry_valid(entry, source, identity):
                    pooled[_sha(source)] = entry
            _save_cache(pool_path, {**pool_identity, "entries": pooled})
    try:
        from ..utils.llm_client import LLMClient
        mapping, _level = translate_pairs(LLMClient(), page, _lang_name(identity["target_lang"]),
            on_failure=failed, on_progress=progress, context=_translation_context(identity),
            identity=durable_identity, seed=seed, force=False)
        progress(mapping)
        cache["page_complete"] = all(key in mapping for key, _ in page)
        if any(key not in mapping for key, _ in page):
            cache["issues"] = ["Some entries in this page remain unreviewed; resume pending work."]
    except Exception as exc:
        cache["issues"] = ["translation worker failed: " + type(exc).__name__]
        logger.warning("Artifact translation worker failed: %s", type(exc).__name__)
    cache.update(updated_at=_now(), call_failures=failures)
    _save_cache(path, cache)
    return _response(cache, identity, pairs)


def graph_translation(graph_id, lang, force=False):
    """Synchronous service entry for the registered worker and offline consumers."""
    return _translate_inventory(*_inventory("graph", graph_id, lang), force=force)


def simulation_translation(sim_id, lang, force=False, *, texts=None, context=None):
    return _translate_inventory(*_inventory("simulation", sim_id, lang, texts, context), force=force)


def _run_overlay(payload):
    from .translation.contracts import TranslationError
    path, identity, pairs = _inventory(payload["kind"], payload["ref_id"], payload["lang"],
                                      payload.get("texts"), payload.get("context"))
    if identity != payload["identity"]:
        raise TranslationError("source_changed", "Translation source changed; refresh the source view.")
    _save_selection(path, identity, pairs)
    with _cache_lock(path):
        # Admission holds this lock until the queued intent is committed. The
        # scheduler can claim immediately after submit, before POST finishes.
        cache = _load_cache(path)
        if cache.get("refresh_generation", 0) != payload.get("refresh_generation", 0):
            raise TranslationError("superseded_refresh", "A newer translation generation owns this selection.")
        # POST already persisted the exact refresh intent. Replaying force here
        # would retranslate a published generation after a completion-window crash.
        result = _translate_inventory_locked(path, identity, pairs, force=False)
    # A page with failures must remain retryable under the same operation. A
    # complete page with a remaining tail is a successful bounded operation;
    # the next POST chooses the next stable page identity.
    page_keys = set(payload["page_keys"])
    if page_keys & (set(result["failed_keys"]) | set(_load_cache(path).get("refresh_pending_keys", []))):
        raise TranslationError("incomplete_page", "Translation page is incomplete; resume its durable pending work.", retryable=True)
    return {"request_digest": identity["request_digest"], "pending": result["pending"],
            "refresh_pending": result["refresh_pending"], "status": "completed"}


def register_translation_handler():
    from .translation.scheduler import register_handler
    from ..api.translations import register_resource_authorizer
    register_handler(_OPERATION, _run_overlay)
    register_resource_authorizer(_OPERATION, _authorize_overlay_operation)


def _authorize_overlay_operation(selection, action):
    """Resolve current source/view authority; a supplied job ID is never proof."""
    if (action not in {"retry", "cancel"} or not isinstance(selection, dict)
            or set(selection) - {"kind", "ref_id", "lang", "request_digest", "context"}
            or selection.get("kind") not in {"graph", "simulation"}):
        return None
    try:
        path, identity, _pairs = _inventory(selection["kind"], selection["ref_id"], selection["lang"],
            context=selection.get("context"), request_digest=selection.get("request_digest"))
        cache = _load_cache(path)
        if not _cache_valid(cache, identity) or not cache.get("translation_job"):
            return None
        operation = _job(cache)
        current = (operation or {}).get("identity")
        if ((operation or {}).get("kind") != _OPERATION or not isinstance(current, dict)
                or any(current.get(key) != value for key, value in identity.items())):
            return None
        return current
    except (KeyError, TypeError, ValueError, OSError):
        return None


def start_translation(kind, ref_id, lang, force=False, *, texts=None, context=None):
    prepared = _inventory(kind, ref_id, lang, texts, context)
    path, identity, pairs = prepared
    # Admission serializes only POST setup. A duplicate never waits behind the
    # worker's long provider/write lock; the first POST commits its job link
    # before the next POST reads it under this short separate lock.
    with _cache_lock(path + ".admission"):
        cache = _load_cache(path)
        if _cache_valid(cache, identity) and cache.get("translation_job"):
            existing = _response(cache, identity, pairs)
            if (existing.get("translation_job") or {}).get("job_state") in {"queued", "running", "waiting_provider"}:
                return {**existing, "started": False}
        return _start_translation(prepared, kind, ref_id, lang, force, texts=texts, context=context)


def _start_translation(prepared, kind, ref_id, lang, force=False, *, texts=None, context=None):
    from .translation.scheduler import submit, retry
    register_translation_handler()
    path, identity, pairs = prepared
    _save_selection(path, identity, pairs)
    with _cache_lock(path):
        cache = _load_cache(path)
        if not _cache_valid(cache, identity):
            cache = {**identity, "entries": {}, "pairs": pairs}
        before = _response(cache, identity, pairs)
        job = before["translation_job"]
        state = (job or {}).get("job_state", (job or {}).get("status"))
        operation = cache.get("translation_job")
        if operation and state in {"queued", "running", "waiting_provider"}:
            return {**before, "started": False}
        if not force and not before["pending"] and not before["refresh_pending"]:
            return {**before, "started": False}
        if force and pairs and not before["pending"] and not before["refresh_pending"]:
            # Persist refresh intent at admission, not only after the worker
            # starts: cancelling a queued refresh must remain resumable.
            cache["refresh_pending_keys"] = [key for key, _ in pairs]
            cache["refresh_generation"] = int(cache.get("refresh_generation", 0)) + 1
            cache["refresh_entries"] = {}
        same_generation = ((job or {}).get("identity") or {}).get("refresh_generation", 0) == cache.get("refresh_generation", 0)
        if operation and same_generation and state in {"interrupted", "failed", "cancelled"}:
            job = retry(job["job_id"])
        else:
            missing = set(before["failed_keys"]) | set(cache.get("refresh_pending_keys", []))
            if not missing and force:
                missing = {key for key, _ in pairs}
            if not missing:
                return {**before, "started": False}
            page_index, page = next((index, page) for index, page in enumerate(_pages(pairs))
                                   if any(key in missing for key, _ in page))
            operation_identity = {**identity, "page": page_index,
                "previous_operation": operation.get("job_id") if operation else None,
                "refresh_generation": int(cache.get("refresh_generation", 0))}
            payload = {"kind": kind, "ref_id": ref_id, "lang": lang, "identity": identity,
                       "texts": texts, "context": context,
                       "refresh_generation": cache.get("refresh_generation", 0),
                       "page_keys": [key for key, _ in page]}
            job = submit(_OPERATION, operation_identity, payload, force=False)
        cache["translation_job"] = job
        _save_cache(path, cache)
    return {**_response(cache, identity, pairs, job=job), "started": True}


def translation_status(kind, ref_id, lang, *, request_digest=None, context=None):
    path, identity, pairs = _inventory(kind, ref_id, lang, context=context, request_digest=request_digest)
    return _response(_load_cache(path), identity, pairs)


def display_document(directory, kind, ref_id, lang, document, *, generate=False, force=False):
    """Separate structured display; canonical numbers, identities and facts are copied."""
    _lang_name(lang)
    pairs = list(_text_paths(document))
    _check_inventory(pairs)
    identity = _identity(kind, ref_id, lang, pairs, {}, _digest(document))
    path = os.path.join(directory, "translations", "display." + _sha(kind + ":" + ref_id)[:24] +
                        "." + lang + "." + identity["request_digest"] + ".json")
    result = (_translate_inventory(path, identity, pairs, force) if generate
              else _response(_load_cache(path), identity, pairs))
    replacements = result["overlay"]
    def project(value, prefix=""):
        if isinstance(value, dict):
            return {key: project(item, prefix + "/" + str(key).replace("~", "~0").replace("/", "~1"))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [project(item, prefix + "/" + str(index)) for index, item in enumerate(value)]
        return replacements.get(prefix, value)
    return {"display": project(document), "translation_job": result["translation_job"],
        "structured_translation": {key: result[key] for key in
            ("status", "partial", "pending", "retryable", "issues", "source_fingerprint", "target_lang", "translation_job")},
        "coverage": {"translated": result["translated"], "total": result["total_candidates"],
                     "complete": not result["pending"] and not result["refresh_pending"]}}
