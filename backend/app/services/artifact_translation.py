"""Validated, source-bound display translations; canonical artifacts stay untouched.

Native overlays retain legacy keys. Visible-text requests are separately cached by
simulation/language/context and inventory digest, so actor/analyst projections can
never leak through a public/default cache read. GET never acquires or translates.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from .translation_tools import translate_pairs

logger = logging.getLogger("mirofish.translation")
_LANGS = {"zh": "简体中文（Simplified Chinese）", "en": "professional analyst-grade English"}
_SIM_ID_RE = re.compile(r"^sim_[A-Za-z0-9_-]{1,64}$")
_GRAPH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_GRAPH_NODES, _MAX_GRAPH_EDGES = 200, 400
_MAX_PAIRS, _MAX_TEXT, _MAX_CHARACTERS = 1200, 32000, 240000
_CACHE_VERSION = 4
_INFLIGHT, _INFLIGHT_LOCK = {}, threading.Lock()


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
    data = _read_json(path)
    return data if isinstance(data, dict) and isinstance(data.get("entries"), dict) else {}


def _save_cache(path, cache):
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


def _graph_pairs(graph_id: str) -> List[Tuple[str, str]]:
    """Collect (overlay_key, source_text) from the graph store, degree-ranked."""
    from .graph_builder import GraphBuilderService  # 延迟导入避免环

    builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
    data = builder.get_graph_data(graph_id, slim=False) or {}
    nodes = list(data.get("nodes") or [])
    edges = list(data.get("edges") or [])
    degree: Dict[str, int] = {}
    for e in edges:
        src = str(e.get("source_node_uuid") or e.get("source") or "")
        dst = str(e.get("target_node_uuid") or e.get("target") or "")
        degree[src] = degree.get(src, 0) + 1
        degree[dst] = degree.get(dst, 0) + 1
    nodes.sort(key=lambda n: -degree.get(str(n.get("uuid") or ""), 0))
    pairs: List[Tuple[str, str]] = []
    for n in nodes[:_MAX_GRAPH_NODES]:
        summary = str(n.get("summary") or "").strip()
        if summary:
            pairs.append((f"node:{n.get('uuid')}:summary", summary))
    for e in edges[:_MAX_GRAPH_EDGES]:
        fact = str(e.get("fact") or "").strip()
        if fact:
            pairs.append((f"edge:{e.get('uuid')}:fact", fact))
    return pairs


def _graph_cache_path(graph_id: str, lang: str) -> Optional[str]:
    if not _GRAPH_ID_RE.match(graph_id or ""):
        return None
    root = getattr(Config, "UPLOAD_FOLDER", "") or "uploads"
    base = os.path.join(os.path.dirname(root), "uploads") if not os.path.isabs(root) else root
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


def _sim_pairs(sim_dir):
    pairs = []
    # world-v1 must use its native visibility-filtered result reader. Never scan
    # actor-state/private raw artifacts as an analyst overlay for the public tab.
    state = _read_json(os.path.join(sim_dir, "state.json")) or {}
    if state.get("simulation_engine") == "world-v1":
        from pathlib import Path
        from .world_simulation.results import read_result
        result = read_result(Path(sim_dir), view="public")
        return [("path:world" + key, value) for key, value in _text_paths(result)]
    world_payload = _read_json(os.path.join(sim_dir, "world_state.json")) or {}
    world = world_payload.get("world", world_payload)
    if isinstance(world, dict):
        if world.get("question"):
            pairs.append(("world:question", str(world["question"])))
        for index, scenario in enumerate(world.get("scenarios") or []):
            name = scenario.get("name") if isinstance(scenario, dict) else scenario
            if isinstance(name, str) and name:
                pairs.append((f"scenario:{index}", name))
        for variable in world.get("variables") or []:
            if not isinstance(variable, dict) or not variable.get("id"):
                continue
            for field in ("name", "rationale"):
                if isinstance(variable.get(field), str) and variable[field]:
                    pairs.append((f"var:{variable['id']}:{field}", variable[field]))
            history = variable.get("history") or []
            cause = history[-1].get("cause") if history and isinstance(history[-1], dict) else None
            if isinstance(cause, str) and cause not in {"seed", "changed", "unchanged"}:
                pairs.append((f"var:{variable['id']}:cause", cause))
    # Aliases stay single translated units, avoiding a second charge for path keys.
    existing = {value for _, value in pairs}
    for key, value in _text_paths(world_payload):
        if value not in existing:
            pairs.append(("path:world" + key, value)); existing.add(value)
    for filename in ("world_digest.jsonl", "world_state_history.jsonl"):
        path = os.path.join(sim_dir, filename)
        if not os.path.isfile(path) or os.path.islink(path) or os.path.getsize(path) > 12000000:
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # a growing JSONL tail is not a corrupt completed row
                if not isinstance(row, dict):
                    continue
                if filename == "world_digest.jsonl" and isinstance(row.get("digest"), str):
                    pairs.append((f"digest:{row.get('round')}", row["digest"]))
                else:
                    pairs.extend((f"path:history/{row.get('round')}" + key, value)
                                 for key, value in _text_paths(row))
    return pairs


def _context(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {
        "engine", "platform", "round", "generation_id", "revision", "view", "actor_id"}:
        raise ValueError("invalid translation context")
    for key, item in value.items():
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
    # Stable surface context lets exact, reviewed visible text survive a live
    # revision/round change. Full request context still owns cache/view privacy.
    return "Human-readable " + identity["kind"] + " display fields. Canonical structured facts are copied separately."


def _entry_valid(entry, source, identity):
    from .model_translation import valid_receipt
    try:
        return (isinstance(entry, dict) and entry.get("sha") == _sha(source)
                and entry.get("text_sha256") == _sha(entry.get("text"))
                and valid_receipt(source, entry.get("text"), identity["target_lang"],
                    entry.get("receipt"), context=_translation_context(identity)))
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def _identity(kind, ref_id, lang, pairs, context):
    return {"schema_version": _CACHE_VERSION, "translation_engine": _model_engine(),
            "kind": kind, "ref_id": ref_id,
            "target_lang": lang, "context": context,
            "request_digest": _digest([kind, ref_id, lang, context, pairs]),
            "source_fingerprint": _digest(pairs)}


def _cache_valid(cache, identity):
    return all(cache.get(key) == value for key, value in identity.items())


def _response(cache, identity, pairs, generating=False):
    # Native inventory changes retain only exact matching source entries. Display
    # documents additionally bind their full numeric/metadata source fingerprint.
    scope_ok = all(cache.get(key) == identity[key] for key in
                   ("schema_version", "translation_engine", "kind", "ref_id", "target_lang", "context"))
    if identity["kind"] not in {"simulation", "graph"}:
        scope_ok = scope_ok and _cache_valid(cache, identity)
    entries = cache.get("entries", {}) if scope_ok else {}
    overlay, translations, failed = {}, [], []
    for key, source in pairs:
        entry = entries.get(key)
        if _entry_valid(entry, source, identity):
            overlay[key] = entry["text"]
            translations.append({"source": source, "text": entry["text"], "source_sha256": _sha(source)})
        else:
            failed.append(key)
    pending = len(failed)
    active_keys = {key for key, _ in pairs}
    refresh_keys = cache.get("refresh_pending_keys") if scope_ok else []
    refresh_pending = len({key for key in refresh_keys if isinstance(key, str) and key in active_keys}) if isinstance(refresh_keys, list) else 0
    incomplete = bool(pending or refresh_pending)
    status = ("generating" if generating else "empty" if not pairs else "available" if not incomplete
              else "partial" if overlay else "failed" if cache.get("attempted") else "unavailable")
    return {**identity, "simulation_id": identity["ref_id"] if identity["kind"] == "simulation" else None,
            "status": status, "overlay": overlay, "translations": translations,
            "translated": len(overlay), "total_candidates": len(pairs), "pending": pending,
            "cached": len(overlay), "partial": incomplete, "retryable": bool(incomplete and not generating),
            "refresh_pending": refresh_pending,
            "failed_keys": failed, "issues": (list(cache.get("issues") or []) or [
                "Some source text remains untranslated; retry pending entries." if pending else
                "A forced refresh is incomplete; previous validated translations are retained."]) if incomplete else [],
            "call_failures": cache.get("call_failures", 0), "model_calls": cache.get("model_calls", 0),
            "updated_at": cache.get("updated_at")}


def _inventory(kind, ref_id, lang, texts=None, context=None, request_digest=None):
    _lang_name(lang)
    if kind == "graph":
        path = _graph_cache_path(ref_id, lang)
        if not path:
            raise ValueError("invalid graph id")
        pairs = _graph_pairs(ref_id)
        return path, _identity(kind, ref_id, lang, pairs, {}), pairs
    if kind != "simulation":
        raise ValueError("unsupported translation kind")
    folder = _sim_dir(ref_id)
    if not folder:
        raise FileNotFoundError("unknown simulation")
    context = _context(context)
    if request_digest is not None:
        if not _DIGEST_RE.fullmatch(request_digest):
            raise ValueError("invalid request digest")
        path = os.path.join(folder, "translations", lang, request_digest + ".json")
        cache = _load_cache(path)
        pairs = cache.get("pairs", [])
        if not isinstance(pairs, list) or len(pairs) > _MAX_PAIRS:
            raise ValueError("invalid translation inventory")
        try:
            pairs = _visible_pairs([value for _, value in pairs])
        except (TypeError, ValueError):
            raise ValueError("invalid translation inventory") from None
        identity = _identity(kind, ref_id, lang, pairs, context)
        if identity["request_digest"] != request_digest or not _cache_valid(cache, identity):
            raise ValueError("translation request context does not match")
    else:
        pairs = _visible_pairs(texts) if texts is not None else _sim_pairs(folder)
        identity = _identity(kind, ref_id, lang, pairs, context)
        path = (os.path.join(folder, "translations", lang, identity["request_digest"] + ".json")
                if texts is not None else os.path.join(folder, "translations", lang + ".json"))
    if len(pairs) > _MAX_PAIRS or sum(len(text) for _, text in pairs) > _MAX_CHARACTERS:
        raise ValueError("translation inventory exceeds limit; request visible texts")
    return path, identity, pairs


def _translate_inventory(path, identity, pairs, force=False):
    # Serialize durable writes/acquisition across workers and process restarts.
    import fcntl
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            return _translate_inventory_locked(path, identity, pairs, force)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _translate_inventory_locked(path, identity, pairs, force=False):
    cache = _load_cache(path)
    if not _cache_valid(cache, identity):
        # Preserve reusable per-source entries while admitting a new native inventory.
        entries = cache.get("entries", {}) if cache.get("schema_version") == _CACHE_VERSION else {}
        cache = {**identity, "entries": entries}
    # Reuse exact validated source text as a live view grows. The pool is an
    # internal lookup, never an API response; only this request's admitted text
    # can be returned, under its own full context/digest identity.
    pool_path = (os.path.join(os.path.dirname(path), ".validated-texts.json")
                 if pairs and all(key.startswith("text:") for key, _ in pairs) else None)
    pool = _load_cache(pool_path) if pool_path else {}
    if (pool.get("schema_version") == _CACHE_VERSION and pool.get("translation_engine") == _model_engine()
            and pool.get("ref_id") == identity["ref_id"]
            and pool.get("target_lang") == identity["target_lang"] and not force):
        for key, source in pairs:
            entry = pool["entries"].get(_sha(source))
            if _entry_valid(entry, source, identity):
                cache["entries"][key] = entry
    before = _response(cache, identity, pairs)
    missing = [(key, source) for key, source in pairs if key not in before["overlay"]]
    active_keys = {key for key, _ in pairs}
    refresh_keys = cache.get("refresh_pending_keys") or []
    refresh_keys = {key for key in refresh_keys if isinstance(key, str) and key in active_keys} if isinstance(refresh_keys, list) else set()
    if missing:
        # Retry/force on a partial inventory repairs missing/invalid values first.
        # It must never spend the bounded budget refreshing the same good prefix.
        pending = missing
    elif refresh_keys:
        pending = [(key, source) for key, source in pairs if key in refresh_keys]
    elif force:
        # An explicit refresh of a complete inventory keeps previous good text.
        # Persist its unfinished tail so a bounded subsequent request can resume.
        pending = list(pairs)
        refresh_keys = active_keys
    else:
        pending = []
    cache["refresh_pending_keys"] = sorted(refresh_keys)
    if not pending:
        cache.update(pairs=pairs, updated_at=_now())
        _save_cache(path, cache)
        return before
    cache.update(attempted=True, pairs=pairs, updated_at=_now(), issues=[])
    failures = 0
    def failed():
        nonlocal failures
        failures += 1
    def progress(mapping):
        receipts = getattr(mapping, "receipts", {})
        admitted = set()
        for key, source in pending:
            value = mapping.get(key)
            if value is not None:
                entry = {"sha": _sha(source), "text": value, "text_sha256": _sha(value),
                         "receipt": receipts.get(key)}
                if _entry_valid(entry, source, identity):
                    cache["entries"][key] = entry
                    admitted.add(key)
        cache["refresh_pending_keys"] = sorted(refresh_keys.difference(admitted))
        cache.update(updated_at=_now(), call_failures=failures,
                     model_calls=getattr(mapping, "calls_used", 0),
                     review_issues=dict(getattr(mapping, "issues", {})))
        _save_cache(path, cache)
        if pool_path:
            import fcntl
            with open(pool_path + ".lock", "a", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    stored = _load_cache(pool_path)
                    pool_entries = stored.get("entries", {}) if stored.get("schema_version") == _CACHE_VERSION else {}
                    pool_entries = {key: entry for key, entry in pool_entries.items()
                                    if isinstance(entry, dict) and isinstance(entry.get("text"), str)}
                    for key, source in pending:
                        if key in admitted:
                            pool_entries[_sha(source)] = cache["entries"][key]
                    # An evicted entry is safely translated again when requested.
                    pool_size = sum(len(entry["text"]) + 220 for entry in pool_entries.values())
                    while len(pool_entries) > 5000 or pool_size > 1800000:
                        removed = pool_entries.pop(next(iter(pool_entries)))
                        pool_size -= len(removed["text"]) + 220
                    _save_cache(pool_path, {"schema_version": _CACHE_VERSION,
                        "translation_engine": _model_engine(), "ref_id": identity["ref_id"], "target_lang": identity["target_lang"], "entries": pool_entries})
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    # Store request identity before acquisition so polling can resolve its inventory.
    _save_cache(path, cache)
    try:
        from ..utils.llm_client import LLMClient
        mapping, _level = translate_pairs(LLMClient(), pending, _lang_name(identity["target_lang"]),
            on_failure=failed, on_progress=progress, context=_translation_context(identity))
        progress(mapping)
        if len(mapping) < len(pending):
            details = []
            for issues in getattr(mapping, "issues", {}).values():
                for issue in issues if isinstance(issues, list) else [issues]:
                    text = str(issue)[:400]
                    if text not in details:
                        details.append(text)
            cache["issues"] = ["Some requested translations are not reviewed as complete; retry pending work. Previous validated text is retained.", *details[:8]]
    except Exception as exc:
        cache["issues"] = ["translation worker failed: " + type(exc).__name__]
        logger.warning("Artifact translation worker failed: %s", type(exc).__name__)
    # Prune removed native keys; stale text is never returned by response either.
    cache["entries"] = {key: cache["entries"][key] for key, _ in pairs if key in cache["entries"]}
    cache.update(updated_at=_now(), call_failures=failures)
    _save_cache(path, cache)
    return _response(cache, identity, pairs)


def graph_translation(graph_id, lang, force=False):
    return _translate_inventory(*_inventory("graph", graph_id, lang), force=force)


def simulation_translation(sim_id, lang, force=False, *, texts=None, context=None):
    return _translate_inventory(*_inventory("simulation", sim_id, lang, texts, context), force=force)


def start_translation(kind, ref_id, lang, force=False, *, texts=None, context=None):
    path, identity, pairs = _inventory(kind, ref_id, lang, texts, context)
    key = (kind, ref_id, lang, identity["request_digest"])
    with _INFLIGHT_LOCK:
        if key in _INFLIGHT:
            return {**_response(_load_cache(path), identity, pairs, True), "started": False}
        cached = _response(_load_cache(path), identity, pairs)
        if not force and not cached["pending"] and not cached["refresh_pending"]:
            return {**cached, "started": False}
        _INFLIGHT[key] = True
        # Persist only this exact caller inventory, never all analyst strings in a default GET.
        cache = _load_cache(path)
        if not _cache_valid(cache, identity):
            cache = {**identity, "entries": {}, "pairs": pairs}
        _save_cache(path, cache)
    ctx = contextvars.copy_context()  # capture caller context, not the new thread's empty context
    def run():
        try:
            ctx.run(_translate_inventory, path, identity, pairs, force)
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.pop(key, None)
    try:
        threading.Thread(target=run, daemon=True, name="artifact-translate-" + kind).start()
    except Exception:
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(key, None)
        raise
    return {**_response(cache, identity, pairs, True), "started": True}


def translation_status(kind, ref_id, lang, *, request_digest=None, context=None):
    path, identity, pairs = _inventory(kind, ref_id, lang, context=context, request_digest=request_digest)
    with _INFLIGHT_LOCK:
        active = (kind, ref_id, lang, identity["request_digest"]) in _INFLIGHT
    return _response(_load_cache(path), identity, pairs, active)


def display_document(directory, kind, ref_id, lang, document, *, generate=False, force=False):
    """A separate display projection with unchanged keys, numeric values and identities."""
    _lang_name(lang)
    pairs = list(_text_paths(document))
    identity = _identity(kind, ref_id, lang, pairs, {})
    # Full canonical payload hash invalidates a projection even when only its numeric
    # context changed; no translated display carries the seal of a different source.
    identity["source_fingerprint"] = _digest(document)
    path = os.path.join(directory, "translations", "display." + _sha(kind + ":" + ref_id)[:24] + "." + lang + ".json")
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
    return {"display": project(document), "structured_translation": {
        key: result[key] for key in ("status", "partial", "pending", "retryable", "issues", "source_fingerprint", "target_lang")},
        "coverage": {"translated": result["translated"], "total": result["total_candidates"],
                     "complete": not result["pending"]}}
