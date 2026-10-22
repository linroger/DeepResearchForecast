"""Graph / simulation artifact translation overlays (2026-10-21).

Extends the bilingual feature beyond the report tab: the knowledge-graph panel
(node summaries / edge facts) and the simulation panel (question, scenario
names, variable names + rationales + latest causes, per-round digests) get the
same language toggle, backed by cached overlay JSON keyed by source-text sha so
re-renders never re-bill and incremental regeneration only touches new/changed
entries. All provider calls run through ``translation_tools.chat_translate``'s
content-compliance ladder, so content-filter rejections (GLM 1301) degrade to
per-fragment fallbacks instead of failing the overlay.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from .translation_tools import translate_pairs

logger = logging.getLogger("mirofish.translation")

_LANGS = {"zh": "简体中文（Simplified Chinese）", "en": "professional analyst-grade English"}
_SIM_ID_RE = re.compile(r"^sim_[A-Za-z0-9_-]{1,64}$")
_GRAPH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

# Bounded inventories: overlays cover what the tabs actually render.
_MAX_GRAPH_NODES = 200
_MAX_GRAPH_EDGES = 400
_MAX_DIGEST_ROWS = 40


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def _lang_name(lang: str) -> str:
    return _LANGS.get(lang, lang)


def _load_cache(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            return data
    except Exception:  # noqa: BLE001 — 缓存坏 → 视为空，重建
        pass
    return {"schema_version": 1, "entries": {}, "updated_at": None}


def _save_cache(path: str, cache: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ────────────────────────────── graph overlays ──────────────────────────────

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
            pairs.append((f"node:{n.get('uuid')}:summary", summary[:1200]))
    for e in edges[:_MAX_GRAPH_EDGES]:
        fact = str(e.get("fact") or "").strip()
        if fact:
            pairs.append((f"edge:{e.get('uuid')}:fact", fact[:600]))
    return pairs


def _graph_cache_path(graph_id: str, lang: str) -> Optional[str]:
    if not _GRAPH_ID_RE.match(graph_id or ""):
        return None
    root = getattr(Config, "UPLOAD_FOLDER", "") or "uploads"
    base = os.path.join(os.path.dirname(root), "uploads") if not os.path.isabs(root) else root
    # uploads/graph_translations/<id>/<lang>.json（UPLOAD_FOLDER 已指向 <app>/../uploads）
    folder = os.path.join(str(Config.UPLOAD_FOLDER), "graph_translations", graph_id)
    return os.path.join(folder, f"{lang}.json")


def graph_translation(graph_id: str, lang: str, force: bool = False) -> Dict[str, Any]:
    """Generate (or load) the graph overlay. Returns {status, overlay, counts}."""
    path = _graph_cache_path(graph_id, lang)
    if path is None:
        return {"status": "error", "error": "invalid graph id"}
    pairs = _graph_pairs(graph_id)
    cache = _load_cache(path)
    entries: Dict[str, Any] = cache["entries"]
    pending = [(k, t) for k, t in pairs if force or entries.get(k, {}).get("sha") != _sha(t)]
    failures = 0

    def _note() -> None:
        nonlocal failures
        failures += 1

    if pending:
        from ..utils.llm_client import LLMClient
        mapping, ladder = translate_pairs(
            LLMClient(), pending, _lang_name(lang), on_failure=_note)
        for k, t in pending:
            if k in mapping:
                entries[k] = {"sha": _sha(t), "text": mapping[k]}
        cache["updated_at"] = _now()
        _save_cache(path, cache)
    overlay = {k: v["text"] for k, v in entries.items()}
    return {
        "status": "available" if overlay else "empty",
        "overlay": overlay,
        "translated": len(overlay),
        "total_candidates": len(pairs),
        "pending": len(pending) if pending else 0,
        "call_failures": failures,
        "cached": len(pairs) - len(pending),
    }


# ──────────────────────────── simulation overlays ───────────────────────────

def _sim_dir(sim_id: str) -> Optional[str]:
    if not _SIM_ID_RE.match(sim_id or ""):
        return None
    d = os.path.join(str(Config.UPLOAD_FOLDER), "simulations", sim_id)
    if not os.path.isdir(d):
        return None
    real = os.path.realpath(d)
    base = os.path.realpath(os.path.join(str(Config.UPLOAD_FOLDER), "simulations"))
    if not real.startswith(base + os.sep):
        return None
    return d


def _sim_pairs(sim_dir: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    ws_path = os.path.join(sim_dir, "world_state.json")
    if os.path.exists(ws_path):
        try:
            w = json.load(open(ws_path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            w = {}
        world = w.get("world") if isinstance(w.get("world"), dict) else w
        q = str(world.get("question") or "").strip()
        if q:
            pairs.append(("world:question", q[:800]))
        for i, sc in enumerate(world.get("scenarios") or []):
            # 场景条目两种形态：dict(name=...) 或裸字符串（本仓两种都出现过）
            name = str((sc.get("name") if isinstance(sc, dict) else sc) or "").strip()
            if name:
                pairs.append((f"scenario:{i}", name[:200]))
        for v in world.get("variables") or []:
            vid = str((v or {}).get("id") or "")
            name = str((v or {}).get("name") or "").strip()
            if vid and name:
                pairs.append((f"var:{vid}:name", name[:200]))
            rationale = str((v or {}).get("rationale") or "").strip()
            if vid and rationale and len(rationale) > 8:
                pairs.append((f"var:{vid}:rationale", rationale[:500]))
            hist = (v or {}).get("history") or []
            if hist:
                cause = str((hist[-1] or {}).get("cause") or "").strip()
                if vid and cause and cause not in ("seed", "changed", "unchanged") and len(cause) > 12:
                    pairs.append((f"var:{vid}:cause", cause[:500]))
    dg_path = os.path.join(sim_dir, "world_digest.jsonl")
    if os.path.exists(dg_path):
        try:
            with open(dg_path, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f
                        if line.strip()][-_MAX_DIGEST_ROWS:]
        except Exception:  # noqa: BLE001
            rows = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            rnd = r.get("round")
            text = str(r.get("digest") or "").strip()
            if text:
                pairs.append((f"digest:{rnd}", text[:1500]))
    return pairs


def simulation_translation(sim_id: str, lang: str, force: bool = False) -> Dict[str, Any]:
    d = _sim_dir(sim_id)
    if d is None:
        return {"status": "error", "error": "unknown simulation"}
    path = os.path.join(d, "translations", f"{lang}.json")
    pairs = _sim_pairs(d)
    cache = _load_cache(path)
    entries: Dict[str, Any] = cache["entries"]
    pending = [(k, t) for k, t in pairs if force or entries.get(k, {}).get("sha") != _sha(t)]
    failures = 0

    def _note() -> None:
        nonlocal failures
        failures += 1

    if pending:
        from ..utils.llm_client import LLMClient
        mapping, _ladder = translate_pairs(
            LLMClient(), pending, _lang_name(lang), on_failure=_note)
        for k, t in pending:
            if k in mapping:
                entries[k] = {"sha": _sha(t), "text": mapping[k]}
        cache["updated_at"] = _now()
        _save_cache(path, cache)
    overlay = {k: v["text"] for k, v in entries.items()}
    return {
        "status": "available" if overlay else "empty",
        "overlay": overlay,
        "translated": len(overlay),
        "total_candidates": len(pairs),
        "pending": len(pending) if pending else 0,
        "call_failures": failures,
        "cached": len(pairs) - len(pending),
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──────────────────────── async generation driver ────────────────────────
# POST 立即返回，生成在后台线程跑（图谱/模拟清单可能有几百条目、几十个批次 LLM 调用，
# 分钟级）；GET 轮询取状态/overlay。contextvars 复制保证计量归属。
import threading as _threading

_INFLIGHT: dict = {}
_INFLIGHT_LOCK = _threading.Lock()


def start_translation(kind: str, ref_id: str, lang: str, force: bool = False) -> Dict[str, Any]:
    """Kick (or join) background generation for 'graph'|'simulation' overlays."""
    key = (kind, ref_id, lang)
    with _INFLIGHT_LOCK:
        if key in _INFLIGHT:
            return {"status": "generating", "started": False}
        _INFLIGHT[key] = {"started_at": _now()}

    def _run() -> None:
        import contextvars as _cv
        ctx = _cv.copy_context()
        try:
            ctx.run(_generate, kind, ref_id, lang, force)
        except Exception as exc:  # noqa: BLE001 — 后台失败落状态，不抛
            logger.error("overlay 翻译后台失败 %s/%s/%s: %s", kind, ref_id, lang, exc)
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.pop(key, None)

    _threading.Thread(target=_run, daemon=True,
                      name=f"overlay-translate-{kind}-{lang}").start()
    return {"status": "generating", "started": True}


def _generate(kind: str, ref_id: str, lang: str, force: bool) -> None:
    if kind == "graph":
        graph_translation(ref_id, lang, force=force)
    else:
        simulation_translation(ref_id, lang, force=force)


def translation_status(kind: str, ref_id: str, lang: str) -> Dict[str, Any]:
    """只读状态：绝不触发生成（GET 轮询用；生成只走 start_translation 的后台线程）。"""
    with _INFLIGHT_LOCK:
        generating = (kind, ref_id, lang) in _INFLIGHT
    if kind == "graph":
        path = _graph_cache_path(ref_id, lang)
        pairs = _graph_pairs(ref_id) if path else []
    else:
        d = _sim_dir(ref_id)
        path = os.path.join(d, "translations", f"{lang}.json") if d else None
        pairs = _sim_pairs(d) if d else []
    if path is None:
        return {"status": "error", "error": "invalid id"}
    cache = _load_cache(path)
    entries = cache.get("entries") or {}
    overlay = {k: v["text"] for k, v in entries.items()}
    cached_hits = sum(1 for k, _t in pairs if entries.get(k, {}).get("sha") == _sha(_t))
    return {
        "status": ("generating" if generating
                   else ("available" if overlay else "empty")),
        "overlay": overlay,
        "translated": len(overlay),
        "total_candidates": len(pairs),
        "cached": cached_hits,
        "pending": len(pairs) - cached_hits,
        "updated_at": cache.get("updated_at"),
    }
