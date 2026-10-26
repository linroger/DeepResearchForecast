"""Per-round index of a platform's social feed (period view of the simulation tab).

The dashboard's World State panel can select any committed period, but the feed beside it
showed the newest posts whatever the period.  OASIS stores posts and comments with the
sandbox clock only, while the runner's ``<platform>/actions.jsonl`` records every
``CREATE_POST`` / ``CREATE_COMMENT`` with the round it happened in, and every
``world_update`` row with the period label of that round.  This module joins the two so
the API can answer "which posts and replies belong to round r" and label the rounds.

Posts are matched to action rows by ``(agent_id, normalised content)``, consuming the
log's occurrences in order so that an agent repeating the same text in two rounds maps
each post to its own round; a post whose content appears once in the log matches by
content alone; anything still unmatched is assigned to the round of the previous matched
post in ``post_id`` order (OASIS ids are monotonic), or the first round.  Comments carry
their ``comment_id`` in the action row.
Everything is read-only and bounded (regular files only, a byte cap on the action log,
read-only SQLite); a missing artefact yields an empty index, never an error.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
import threading
from collections import OrderedDict, deque
from typing import Any, Dict, List, Optional, Tuple

FEED_ACTIONS_MAX_BYTES = 64 * 1024 * 1024
FEED_CONTENT_KEY_CHARS = 2000
_CACHE_MAX = 16
_WS_RE = re.compile(r"\s+")

_cache: "OrderedDict[Tuple[str, str, Tuple[int, int, int, int]], Dict[str, Any]]" = OrderedDict()
_cache_lock = threading.Lock()


def _norm(text: Any) -> str:
    return _WS_RE.sub(" ", str(text if text is not None else "")).strip()[:FEED_CONTENT_KEY_CHARS]


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _regular_file(path: str) -> bool:
    return bool(path) and not os.path.islink(path) and os.path.isfile(path)


def read_action_rounds(actions_path: str, *, max_bytes: int = FEED_ACTIONS_MAX_BYTES) -> Dict[str, Any]:
    """Round facts from a platform action log, streamed line by line.

    Returns ``rounds`` (round → {period_label, headline, simulated_hour}), ``post_keys``
    ((agent_id, content) → rounds in log order), ``content_rounds`` (content → rounds in
    log order), ``comment_rounds`` (comment_id → round), ``comment_keys`` ((agent_id,
    content) → rounds in log order) and ``truncated``.  The round queues are consumed by
    ``build_feed_round_index`` in id order.
    """
    out: Dict[str, Any] = {"rounds": {}, "post_keys": {}, "content_rounds": {}, "comment_rounds": {},
                           "comment_keys": {}, "truncated": False}
    if not _regular_file(actions_path):
        return out
    read = 0
    try:
        with open(actions_path, "r", encoding="utf-8") as f:
            for line in f:
                read += len(line.encode("utf-8", "replace"))
                if read > max_bytes:
                    out["truncated"] = True
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                rnd = _as_int(row.get("round"))
                if rnd is None:
                    continue
                kind = row.get("event_type") or row.get("action_type")
                if kind == "round_start":
                    out["rounds"].setdefault(rnd, {})["simulated_hour"] = row.get("simulated_hour")
                    continue
                if kind == "world_update":
                    entry = out["rounds"].setdefault(rnd, {})
                    if row.get("period_label"):
                        entry["period_label"] = str(row.get("period_label"))[:40]
                    if row.get("headline"):
                        entry["headline"] = str(row.get("headline"))[:300]
                    continue
                if kind not in ("CREATE_POST", "CREATE_COMMENT") or row.get("success") is False:
                    continue
                out["rounds"].setdefault(rnd, {})
                args = row.get("action_args") if isinstance(row.get("action_args"), dict) else {}
                content = _norm(args.get("content"))
                agent = _as_int(row.get("agent_id"))
                if kind == "CREATE_POST":
                    if content:
                        out["post_keys"].setdefault((agent, content), deque()).append(rnd)
                        out["content_rounds"].setdefault(content, deque()).append(rnd)
                else:
                    cid = args.get("comment_id")
                    if cid not in (None, ""):
                        out["comment_rounds"].setdefault(str(cid), rnd)
                    if content:
                        out["comment_keys"].setdefault((agent, content), deque()).append(rnd)
    except OSError:
        return {"rounds": {}, "post_keys": {}, "content_rounds": {}, "comment_rounds": {},
                "comment_keys": {}, "truncated": False}
    return out


def _take(queues: Dict[Any, "deque"], key: Any) -> Optional[int]:
    """Pop the next recorded round for ``key`` (None when the key is unknown or exhausted)."""
    queue = queues.get(key)
    if not queue:
        return None
    return queue.popleft()


def load_platform_rows(db_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[int, int]]:
    """(posts, comments, user_id → agent_id) from a platform SQLite file, read-only."""
    if not _regular_file(db_path):
        return [], [], {}
    uri = Path(db_path).absolute().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error:
        return [], [], {}
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            posts = [dict(r) for r in cur.execute("SELECT post_id, user_id, content FROM post ORDER BY post_id")]
        except sqlite3.Error:
            posts = []
        try:
            comments = [dict(r) for r in cur.execute(
                "SELECT comment_id, post_id, user_id, content FROM comment ORDER BY comment_id")]
        except sqlite3.Error:
            comments = []
        agents: Dict[int, int] = {}
        try:
            for r in cur.execute("SELECT user_id, agent_id FROM user"):
                uid, aid = _as_int(r["user_id"]), _as_int(r["agent_id"])
                if uid is not None and aid is not None:
                    agents[uid] = aid
        except sqlite3.Error:
            pass
        return posts, comments, agents
    finally:
        conn.close()


def build_feed_round_index(sim_dir: str, platform: str) -> Dict[str, Any]:
    """The index for one platform of a run (empty ``rounds`` when the artefacts are missing)."""
    platform = str(platform or "")
    actions_path = os.path.join(sim_dir, platform, "actions.jsonl")
    db_path = os.path.join(sim_dir, f"{platform}_simulation.db")
    acts = read_action_rounds(actions_path)
    posts, comments, agents = load_platform_rows(db_path)
    post_round: Dict[int, int] = {}
    comment_round: Dict[int, int] = {}
    unmatched_posts = 0
    unmatched_comments = 0
    rounds_sorted = sorted(acts["rounds"])
    first_round = rounds_sorted[0] if rounds_sorted else 0
    previous = first_round
    for post in posts:
        pid = _as_int(post.get("post_id"))
        if pid is None:
            continue
        uid = _as_int(post.get("user_id"))
        agent = agents.get(uid, uid)
        content = _norm(post.get("content"))
        rnd = _take(acts["post_keys"], (agent, content))
        if rnd is None and content and len(acts["content_rounds"].get(content) or ()) == 1:
            rnd = _take(acts["content_rounds"], content)
        if rnd is None:
            rnd = previous
            unmatched_posts += 1
        post_round[pid] = rnd
        previous = rnd
    previous = first_round
    for comment in comments:
        cid = _as_int(comment.get("comment_id"))
        if cid is None:
            continue
        rnd = acts["comment_rounds"].get(str(cid))
        if rnd is None:
            uid = _as_int(comment.get("user_id"))
            rnd = _take(acts["comment_keys"], (agents.get(uid, uid), _norm(comment.get("content"))))
        if rnd is None:
            rnd = previous
            unmatched_comments += 1
        comment_round[cid] = rnd
        previous = rnd
    counts_p: Dict[int, int] = {}
    counts_c: Dict[int, int] = {}
    for rnd in post_round.values():
        counts_p[rnd] = counts_p.get(rnd, 0) + 1
    for rnd in comment_round.values():
        counts_c[rnd] = counts_c.get(rnd, 0) + 1
    all_rounds = sorted(set(rounds_sorted) | set(counts_p) | set(counts_c))
    rounds = []
    for rnd in all_rounds:
        meta = acts["rounds"].get(rnd, {})
        rounds.append({
            "round": rnd,
            "period_label": meta.get("period_label") or "",
            "headline": meta.get("headline") or "",
            "posts": counts_p.get(rnd, 0),
            "comments": counts_c.get(rnd, 0),
        })
    return {
        "platform": platform,
        "rounds": rounds,
        "post_round": post_round,
        "comment_round": comment_round,
        "unmatched_posts": unmatched_posts,
        "unmatched_comments": unmatched_comments,
        "truncated": bool(acts["truncated"]),
    }


def _stamp(path: str) -> Tuple[int, int]:
    try:
        st = os.stat(path)
        return int(st.st_mtime_ns), int(st.st_size)
    except OSError:
        return (0, 0)


def cached_feed_round_index(sim_dir: str, platform: str) -> Dict[str, Any]:
    """``build_feed_round_index`` memoised on the action log's and database's mtime/size."""
    platform = str(platform or "")
    key = (os.path.abspath(sim_dir), platform,
           _stamp(os.path.join(sim_dir, platform, "actions.jsonl"))
           + _stamp(os.path.join(sim_dir, f"{platform}_simulation.db")))
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    index = build_feed_round_index(sim_dir, platform)
    with _cache_lock:
        _cache[key] = index
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return index


def public_index(index: Dict[str, Any]) -> Dict[str, Any]:
    """The index without the per-id maps (what the feed-rounds endpoint returns)."""
    return {k: v for k, v in index.items() if k not in ("post_round", "comment_round")}


def ids_for_round(index: Dict[str, Any], rnd: int, comments: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
    """(post ids, comment ids) that belong to round ``rnd``: posts created in it plus the
    parents of comments made in it; ``comments`` are rows with comment_id/post_id."""
    comment_ids = sorted(cid for cid, r in index.get("comment_round", {}).items() if r == rnd)
    wanted = set(comment_ids)
    post_ids = {pid for pid, r in index.get("post_round", {}).items() if r == rnd}
    for c in comments:
        if _as_int(c.get("comment_id")) in wanted and _as_int(c.get("post_id")) is not None:
            post_ids.add(_as_int(c.get("post_id")))
    return sorted(post_ids), comment_ids
