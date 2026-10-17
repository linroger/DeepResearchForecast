"""Period view of the simulation feed: posts and replies indexed by the round they were
written in (``services.feed_rounds``) and served per round by the simulation API.

The dashboard's World State panel selects a committed period; the feed must show that
period's posts (and the threads replied to in it) instead of the newest posts.  Pins: action
rows map posts by (agent, content) and comments by id, content-only and previous-round
fallbacks stay honest about unmatched rows, period labels come from the world_update rows,
the per-round endpoints return exactly the round's rows with their ``round`` and the
legacy endpoints are untouched without ``round``; containment and bounds hold.
"""

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import feed_rounds as fr  # noqa: E402


def _row(round_, agent, kind, **args):
    return {"round": round_, "timestamp": "2026-10-17T00:00:00", "agent_id": agent, "agent_name": f"Agent{agent}",
            "action_type": kind, "action_args": args, "result": None, "success": True}


def _write_run(sim_dir, platform="twitter", *, with_actions=True, symlink_actions=False):
    os.makedirs(os.path.join(sim_dir, platform), exist_ok=True)
    rows = [
        {"timestamp": "t", "event_type": "simulation_start", "platform": platform, "total_rounds": 3},
        {"round": 0, "event_type": "round_start", "simulated_hour": 0},
        _row(0, 6, "CREATE_POST", content="The cliff is here.\n\nStatutory controls now."),
        _row(0, 0, "CREATE_POST", content="MOFCOM's position is consistent."),
        {"round": 0, "event_type": "round_end", "actions_count": 2},
        {"round": 1, "event_type": "round_start", "simulated_hour": 1},
        {"round": 1, "event_type": "world_update", "period_label": "2026-11", "headline": "2026-11: 3 decisions"},
        _row(1, 2, "CREATE_POST", content="Case-by-case review continues."),
        _row(1, 1, "CREATE_COMMENT", content="Noted, Bureau.", comment_id="1"),
        _row(1, 3, "CREATE_POST", content="Shared text", ),
        {"round": 1, "event_type": "round_end", "actions_count": 3},
        {"round": 2, "event_type": "round_start", "simulated_hour": 2},
        {"round": 2, "event_type": "world_update", "period_label": "2026-12", "headline": "2026-12: deal"},
        _row(2, 3, "CREATE_POST", content="Shared text"),                      # same text as round 1 → ambiguous
        _row(2, 4, "CREATE_COMMENT", content="Verification first."),             # no comment_id → key match
        _row(2, 5, "CREATE_POST", content="Failed post", ) | {"success": False},
        {"round": 2, "event_type": "round_end", "actions_count": 3},
        "not json",
        json.dumps({"round": "x", "action_type": "CREATE_POST"}),
    ]
    if with_actions:
        path = os.path.join(sim_dir, platform, "actions.jsonl")
        if symlink_actions:
            real = os.path.join(sim_dir, "real_actions.jsonl")
            with open(real, "w", encoding="utf-8") as f:
                f.write("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n")
            os.symlink(real, path)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n")
    db = sqlite3.connect(os.path.join(sim_dir, f"{platform}_simulation.db"))
    db.executescript("""
        CREATE TABLE user (user_id INTEGER PRIMARY KEY, agent_id INTEGER, user_name TEXT, name TEXT);
        CREATE TABLE post (post_id INTEGER PRIMARY KEY, user_id INTEGER, original_post_id INTEGER, content TEXT,
                           quote_content TEXT, created_at TEXT, num_likes INTEGER DEFAULT 0);
        CREATE TABLE comment (comment_id INTEGER PRIMARY KEY, post_id INTEGER, user_id INTEGER, content TEXT,
                              created_at TEXT, num_likes INTEGER DEFAULT 0);
    """)
    # user ids are shifted by 10 so that the user → agent mapping is exercised
    db.executemany("INSERT INTO user VALUES (?,?,?,?)", [(10 + a, a, None, f"agent_{a}") for a in range(7)])
    db.executemany("INSERT INTO post (post_id, user_id, content, created_at) VALUES (?,?,?,?)", [
        (1, 16, "The cliff is here.\n\nStatutory controls now.", "2026-10-17 00:52:18"),
        (2, 10, "MOFCOM's position is   consistent.", "2026-10-17 00:52:19"),      # whitespace differs
        (3, 12, "Case-by-case review continues.", "2026-10-17 01:52:18"),
        (4, 13, "Shared text", "2026-10-17 01:52:19"),                               # first occurrence → round 1
        (5, 11, "Not in the log at all", "2026-10-17 01:52:20"),                     # unmatched → previous (1)
        (6, 13, "Shared text", "2026-10-17 02:52:18"),                               # second occurrence → round 2
    ])
    db.executemany("INSERT INTO comment (comment_id, post_id, user_id, content, created_at) VALUES (?,?,?,?,?)", [
        (1, 3, 11, "Noted, Bureau.", "2026-10-17 01:53:00"),
        (2, 1, 14, "Verification first.", "2026-10-17 02:53:00"),
        (3, 2, 15, "Orphan reply", "2026-10-17 02:54:00"),
    ])
    db.commit()
    db.close()


def test_index_maps_posts_by_agent_and_content_and_comments_by_id(tmp_path):
    sim_dir = str(tmp_path / "sim_a")
    _write_run(sim_dir)
    idx = fr.build_feed_round_index(sim_dir, "twitter")
    assert idx["post_round"] == {1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 2}
    assert idx["comment_round"] == {1: 1, 2: 2, 3: 2}
    assert idx["unmatched_posts"] == 1 and idx["unmatched_comments"] == 1
    assert idx["truncated"] is False
    rounds = {r["round"]: r for r in idx["rounds"]}
    assert sorted(rounds) == [0, 1, 2]
    assert rounds[1]["period_label"] == "2026-11" and rounds[1]["headline"] == "2026-11: 3 decisions"
    assert rounds[0]["period_label"] == "" and rounds[0]["posts"] == 2
    assert rounds[1]["posts"] == 3 and rounds[1]["comments"] == 1 and rounds[2]["posts"] == 1 and rounds[2]["comments"] == 2
    # posts of round 2: the one created in it plus the two threads replied to in it
    post_ids, comment_ids = fr.ids_for_round(idx, 2, fr.load_platform_rows(os.path.join(sim_dir, "twitter_simulation.db"))[1])
    assert post_ids == [1, 2, 6] and comment_ids == [2, 3]
    assert fr.public_index(idx).keys() == {"platform", "rounds", "unmatched_posts", "unmatched_comments", "truncated"}


def test_missing_symlinked_or_oversized_artefacts_yield_an_empty_or_db_only_index(tmp_path):
    empty = str(tmp_path / "sim_empty")
    os.makedirs(empty)
    idx = fr.build_feed_round_index(empty, "twitter")
    assert idx["rounds"] == [] and idx["post_round"] == {}
    linked = str(tmp_path / "sim_link")
    _write_run(linked, symlink_actions=True)
    idx = fr.build_feed_round_index(linked, "twitter")
    assert idx["rounds"] and all(r["period_label"] == "" for r in idx["rounds"])  # log ignored, posts fall back
    assert idx["unmatched_posts"] == 6 and set(idx["post_round"].values()) == {0}
    big = str(tmp_path / "sim_big")
    _write_run(big)
    acts = fr.read_action_rounds(os.path.join(big, "twitter", "actions.jsonl"), max_bytes=200)
    assert acts["truncated"] is True


def test_cache_follows_the_artefacts(tmp_path):
    sim_dir = str(tmp_path / "sim_c")
    _write_run(sim_dir)
    first = fr.cached_feed_round_index(sim_dir, "twitter")
    assert fr.cached_feed_round_index(sim_dir, "twitter") is first
    with open(os.path.join(sim_dir, "twitter", "actions.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"round": 3, "event_type": "round_start", "simulated_hour": 3}) + "\n")
    os.utime(os.path.join(sim_dir, "twitter", "actions.jsonl"), (1, 1))
    second = fr.cached_feed_round_index(sim_dir, "twitter")
    assert second is not first and [r["round"] for r in second["rounds"]] == [0, 1, 2, 3]


# ----------------------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_feed_rounds_endpoint_and_per_round_posts_and_comments(client, tmp_path):
    _write_run(str(tmp_path / "sim_api"))
    res = client.get("/api/simulation/sim_api/feed-rounds?platform=twitter")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert [r["round"] for r in data["rounds"]] == [0, 1, 2]
    assert data["rounds"][2]["period_label"] == "2026-12" and "post_round" not in data

    res = client.get("/api/simulation/sim_api/posts?platform=twitter&round=1&limit=10")
    data = res.get_json()["data"]
    assert data["round"] == 1 and data["period_label"] == "2026-11" and data["total"] == 3
    assert [p["post_id"] for p in data["posts"]] == [5, 4, 3]                    # newest first within the round
    assert all(p["round"] == 1 for p in data["posts"])
    res = client.get("/api/simulation/sim_api/posts?platform=twitter&round=2")
    data = res.get_json()["data"]
    assert [p["post_id"] for p in data["posts"]] == [6, 2, 1] and [p["round"] for p in data["posts"]] == [2, 0, 0]
    res = client.get("/api/simulation/sim_api/comments?platform=twitter&round=2")
    data = res.get_json()["data"]
    assert [c["comment_id"] for c in data["comments"]] == [3, 2] and all(c["round"] == 2 for c in data["comments"])
    assert client.get("/api/simulation/sim_api/posts?platform=twitter&round=7").get_json()["data"]["posts"] == []
    # paging inside a round
    data = client.get("/api/simulation/sim_api/posts?platform=twitter&round=1&limit=2&offset=2").get_json()["data"]
    assert [p["post_id"] for p in data["posts"]] == [3] and data["total"] == 3


def test_round_filter_validation_and_containment(client, tmp_path):
    _write_run(str(tmp_path / "sim_v"))
    assert client.get("/api/simulation/sim_v/posts?platform=twitter&round=abc").status_code == 400
    assert client.get("/api/simulation/sim_v/posts?platform=../x&round=1").status_code == 400
    assert client.get("/api/simulation/nope/posts?platform=twitter&round=1").status_code == 404
    assert client.get("/api/simulation/..%2F..%2Fetc/feed-rounds").status_code == 404
    assert client.get("/api/simulation/nope/feed-rounds").status_code == 404
    os.makedirs(str(tmp_path / "sim_fresh"))
    assert client.get("/api/simulation/sim_fresh/feed-rounds?platform=twitter").get_json()["data"]["rounds"] == []


def test_legacy_endpoints_without_round_are_unchanged(client, tmp_path, monkeypatch):
    # the legacy routes resolve the directory relative to the API module; point both at tmp
    import app.api.simulation as api_mod
    real_join = os.path.join

    def _join(*parts):
        if len(parts) == 2 and str(parts[1]).startswith("../../uploads/simulations/"):
            return real_join(str(tmp_path), str(parts[1]).split("/")[-1])
        return real_join(*parts)

    monkeypatch.setattr(api_mod.os.path, "join", _join)
    _write_run(str(tmp_path / "sim_legacy"))
    data = client.get("/api/simulation/sim_legacy/posts?platform=twitter&limit=3").get_json()["data"]
    assert data["total"] == 6 and [p["post_id"] for p in data["posts"]] == [6, 5, 4] and "round" not in data
    assert "round" not in data["posts"][0]
    data = client.get("/api/simulation/sim_legacy/comments?platform=twitter").get_json()["data"]
    assert data["count"] == 3 and "round" not in data["comments"][0]
