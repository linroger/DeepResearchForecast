"""Authoritative simulation sources for the guarded translation browser server.

Call ``install_simulations(root, monkeypatch, app, model)`` only AFTER installing
main_offline_guard and creating the real Flask app. It returns JSON-safe
``{graph: {graph_id, nodes, edges, ...}, ids: {oasis, world, record}}``. Keep the
MonkeyPatch alive for the server lifetime. ``model`` is deliberately untouched:
the server owns the controlled provider, scheduler and fault injection.

Injected source boundaries, exhaustively:
* GraphBuilderService._fetch_graph_raw supplies one synthetic full graph (1000
  node summaries plus one edge fact). Actual full/slim/top-K/detail/neighborhood
  readers, graph routes, inventory resolver, scheduler and persistence stay real.
* Config/manager/runner simulation roots point to root/uploads/simulations.
  The simulation API module's __file__ is redirected to root/app/api/simulation.py
  solely because unfiltered legacy posts/comments resolve ../../uploads relative
  to that file. Their actual SQLite queries and translation admission now read
  the SAME fixture databases. No route or source-reader function is replaced.
* A fixture-only sqlite3.connect path adapter canonicalizes the legacy reader's
  exact file:/absolute?mode=ro spelling to Path.as_uri() ONLY for existing regular
  files with canonical real paths below this fixture's simulation root. It calls
  the original sqlite3.connect, so the unchanged audit guard still checks the
  canonical URI and filesystem. No new guard permission or SQL stub is installed.
* OASIS profiles, SQLite feed, action logs and world-state/history/digest are
  synthetic persisted source files. World and record use real preparation,
  ExamplePolicy, run_child, committed SQLite results and public/actor/analyst
  readers. The record additionally uses the real locked publisher and audit.

All runtime output stays below root. There is no provider call, network bind,
subprocess launch, saved-run read or test-owned lifecycle stub in this installer.
This fixture establishes wiring and integrity, never model translation quality.
"""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import unquote, urlsplit


GRAPH_ID = "graph_browser_translation"
IDS = {"oasis": "sim_browser_oasis", "world": "sim_browser_world", "record": "sim_browser_record"}


def _install_readonly_uri_adapter(sim_root, monkeypatch):
    """Adapt one legacy URI spelling; invalid requests still reach the guard."""
    original_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        uri_enabled = kwargs.get("uri", args[6] if len(args) > 6 else False)
        if (uri_enabled and isinstance(database, str) and database.startswith("file:/")
                and not database.startswith("file://")):
            parsed = urlsplit(database)
            decoded = unquote(parsed.path, errors="strict")
            if (parsed.scheme == "file" and not parsed.netloc and not parsed.fragment
                    and parsed.query == "mode=ro" and "\x00" not in decoded):
                candidate = Path(decoded)
                # Match precisely the production reader's path encoding; reject
                # aliases, symlinks, encoded separators and traversal spellings.
                legacy = "file:" + candidate.as_posix().replace("?", "%3F") + "?mode=ro"
                if (database == legacy and candidate.is_absolute()
                        and candidate.is_relative_to(sim_root)
                        and candidate.resolve() == candidate and candidate.is_file()):
                    database = candidate.as_uri() + "?mode=ro"
                    sys.modules["main_offline_guard"].record("fixture:readonly_sqlite_uri_normalized")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _graph():
    nodes = [{"uuid": f"browser-node-{i:04d}", "name": f"Browser supplier {i:04d}",
              "labels": ["Entity", "Organization"], "attributes": {},
              "summary": f"Browser supplier {i} plans capacity of 12 MW under declared assumptions."}
             for i in range(1000)]
    edges = [{"uuid": "browser-edge-tail", "name": "SUPPLIES", "source_node_uuid": nodes[0]["uuid"],
              "target_node_uuid": nodes[1]["uuid"], "source_node_name": nodes[0]["name"],
              "target_node_name": nodes[1]["name"], "attributes": {},
              "fact": "The final graph relationship supplies 25 MW under a conditional agreement."}]
    return {"graph_id": GRAPH_ID, "nodes": nodes, "edges": edges,
            "node_count": len(nodes), "edge_count": len(edges), "total_node_count": len(nodes),
            "total_edge_count": len(edges), "truncated": False}


def _install_oasis(directory, manager):
    from app.services.simulation_manager import SimulationState, SimulationStatus
    from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner

    sid = directory.name
    state = SimulationState(simulation_id=sid, project_id="project_browser", graph_id=GRAPH_ID,
        simulation_engine="oasis-legacy", status=SimulationStatus.COMPLETED,
        profiles_count=2, entities_count=2, current_round=2,
        twitter_status="completed", reddit_status="completed")
    manager._save_simulation_state(state)
    profiles = [
        {"user_id": 1, "agent_id": 1, "name": "Supplier", "type": "company",
         "bio": "The supplier plans a phased expansion of 12 MW."},
        {"user_id": 2, "agent_id": 2, "name": "Buyer", "type": "company",
         "bio": "The buyer evaluates delivery commitments and available capacity."},
    ]
    _json(directory / "reddit_profiles.json", profiles)
    with (directory / "twitter_profiles.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(profiles[0]))
        writer.writeheader()
        writer.writerows(profiles)
    for platform in ("twitter", "reddit"):
        posts = [(1, 1, "The supplier announces capacity of 12 MW.", "2030-01-01T01:00:00Z", 3),
                 (2, 2, "The buyer requests delivery of 25 MW.", "2030-01-02T01:00:00Z", 4)]
        comments = [(1, 1, 2, "The buyer requests confirmation of the permit.", "2030-01-01T02:00:00Z"),
                    (2, 1, 1, "The supplier confirms a conditional delivery plan.", "2030-01-02T02:00:00Z")]
        with sqlite3.connect(directory / f"{platform}_simulation.db") as db:
            db.executescript("""
                CREATE TABLE user (user_id INTEGER PRIMARY KEY, agent_id INTEGER, name TEXT);
                CREATE TABLE post (post_id INTEGER PRIMARY KEY, user_id INTEGER, content TEXT,
                                   created_at TEXT, num_likes INTEGER);
                CREATE TABLE comment (comment_id INTEGER PRIMARY KEY, post_id INTEGER,
                                      user_id INTEGER, content TEXT, created_at TEXT);
            """)
            db.executemany("INSERT INTO user VALUES (?, ?, ?)", [(1, 1, "Supplier"), (2, 2, "Buyer")])
            db.executemany("INSERT INTO post VALUES (?, ?, ?, ?, ?)", posts)
            db.executemany("INSERT INTO comment VALUES (?, ?, ?, ?, ?)", comments)
        actions = []
        for index, (post, comment) in enumerate(zip(posts, comments), start=1):
            actions.extend([
                {"event_type": "world_update", "round": index, "period_label": f"2030-01-0{index}",
                 "headline": f"Period {index}: a conditional delivery plan remains under discussion."},
                {"action_type": "CREATE_POST", "round": index, "platform": platform,
                 "agent_id": post[1], "agent_name": profiles[post[1] - 1]["name"],
                 "action_args": {"content": post[2]}, "timestamp": post[3], "success": True},
                {"action_type": "CREATE_COMMENT", "round": index, "platform": platform,
                 "agent_id": comment[2], "agent_name": profiles[comment[2] - 1]["name"],
                 "action_args": {"comment_id": comment[0], "post_id": comment[1], "content": comment[3]},
                 "timestamp": comment[4], "success": True},
            ])
        _jsonl(directory / platform / "actions.jsonl", actions)
    history = [{"round": round_index, "period_label": f"2030-01-0{round_index}",
                "headline": f"Period {round_index}: the permit changes modeled capacity.",
                "narrative": f"The public authority reviews expansion in period {round_index}.",
                "arbiter_status": "applied", "arbiter_problems": [],
                "decisions": {"total": 2, "ok": 2, "held": 0, "failed": 0, "invalid": 0},
                "diff": {"variables_changed": [{"id": "capacity", "name": "Production capacity",
                         "from": 10 + round_index, "to": 11 + round_index, "unit": "MW"}],
                         "variables_added": [], "relationships_changed": []},
                "deterministic": {"actions": ["Supplier publishes the expansion schedule."],
                                  "effects_fired": [], "scheduled_events": [], "commitments_lapsed": []}}
               for round_index in (1, 2)]
    digest = "The permit remains conditional; modeled production capacity is 13 MW."
    _json(directory / "world_state.json", {"simulation_id": sid, "committed_round": 2,
        "headline": history[-1]["headline"], "digest": digest, "summary": {"arbiter_failed_rounds": 0},
        "world": {"question": "How does conditional capacity change?", "as_of_date": "2030-01-01",
                  "horizon_date": "2030-01-03", "period": {"label": "2030-01-02"},
                  "variables": [{"id": "capacity", "name": "Production capacity", "value": 13,
                      "unit": "MW", "kind": "numeric", "as_of": "2030-01-02",
                      "provenance": "Derived from the public permit assumptions [S1].",
                      "history": [{"round": 0, "value": 10}, {"round": 1, "value": 12}, {"round": 2, "value": 13}]}],
                  "actors": [{"agent_id": 1, "name": "Supplier", "commitments": []}],
                  "relationships": [], "pending_effects": [], "events": [], "seed_gaps": []}})
    _jsonl(directory / "world_state_history.jsonl", history)
    _jsonl(directory / "world_digest.jsonl", [{"round": 1, "digest": "The supplier plans capacity of 12 MW."},
                                               {"round": 2, "digest": digest}])
    SimulationRunner._save_run_state(SimulationRunState(simulation_id=sid,
        runner_status=RunnerStatus.COMPLETED, current_round=2, total_rounds=2,
        twitter_enabled=True, reddit_enabled=True, twitter_completed=True, reddit_completed=True,
        twitter_actions_count=4, reddit_actions_count=4), force=True)


def _install_world(directory, manager, *, publish_record=False):
    from app.services.simulation_manager import SimulationState
    from app.services.simulation_runner import SimulationRunner
    from app.services.world_simulation.examples import ExamplePolicy, example_spec
    from app.services.world_simulation.service import run_child

    # Same preparation and controller path as test_world_service_results.prepare,
    # with an explicitly saved fixed ID rather than UUID monkeypatching.
    sid = directory.name
    manager._save_simulation_state(SimulationState(simulation_id=sid, project_id="project_browser",
        graph_id=GRAPH_ID, simulation_engine="world-v1", enable_twitter=False, enable_reddit=False))
    spec = example_spec("investment")
    spec.pop("simulationId")
    spec.pop("generationId")
    manager.prepare_world_simulation(sid, raw_spec=spec,
        research_report="Synthetic browser fixture; all mechanism values are assumptions.",
        research_generation_id="research_browser_fixture", research_engine="v3")
    if run_child(directory, policy=ExamplePolicy("investment")) != 0:
        raise AssertionError(f"Synthetic world did not commit: {sid}")
    if publish_record and not SimulationRunner.publish_simulation_record(
            sid, language="en", engine_hint="world-v1", synthesis=False):
        raise AssertionError(f"Synthetic record did not pass publication: {sid}")


def install_simulations(root, monkeypatch, app, model):
    """Install isolated sources; return the real graph read and stable simulation IDs.

    GET /api/graph/data/<graph>?full=true reads all 1001 graph prose fields.
    GET /api/simulation/<ids.oasis> and its profiles/posts/comments/world-state
    routes read the disk fixture. ids.world serves public/actor/analyst /world
    rounds 0..4 (actor example: buyer). ids.record serves an audited /record and
    /record.md; its canonical JSON supplies revision via compact JSON.stringify
    ([config_hash || '', generator_version || '', generated_at || '']).
    Translation POST/GET endpoints are the unmodified resource routes. The
    caller must not wrap this installer with app creation or provider stubs.
    """
    guard = sys.modules.get("main_offline_guard")
    root = Path(root).resolve()
    if guard is None or not root.is_relative_to(Path(guard.root).resolve()):
        raise RuntimeError("Install the main offline guard before simulation fixture imports")
    # Application imports deliberately remain below the guard check.
    from app.api import simulation as simulation_api
    from app.config import Config
    from app.services.graph_builder import GraphBuilderService
    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner

    sim_root = root / "uploads" / "simulations"
    for sid in IDS.values():
        if (sim_root / sid).exists():
            raise FileExistsError(f"Refusing to replace an existing simulation fixture: {sid}")
    _install_readonly_uri_adapter(sim_root, monkeypatch)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sim_root))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sim_root))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(sim_root))
    monkeypatch.setattr(Config, "SIM_RECORD_ENABLED", True)
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    # The real legacy route queries are source-relative, unlike their admission
    # readers. Redirect the path anchor without replacing the API function.
    api_anchor = root / "app" / "api"
    api_anchor.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(simulation_api, "__file__", str(api_anchor / "simulation.py"))

    graph = _graph()
    def graph_source(_self, graph_id, **_options):
        if graph_id != GRAPH_ID:
            raise FileNotFoundError("Unknown browser fixture graph")
        return copy.deepcopy(graph)
    monkeypatch.setattr(GraphBuilderService, "_fetch_graph_raw", graph_source)
    # This facade accepts an unused legacy key even for the local graph backend.
    monkeypatch.setattr(Config, "ZEP_API_KEY", "browser-fixture-not-a-credential")
    manager = SimulationManager()
    _install_oasis(sim_root / IDS["oasis"], manager)
    _install_world(sim_root / IDS["world"], manager)
    _install_world(sim_root / IDS["record"], manager, publish_record=True)

    # Fail installation at the actual consumer if a source format drifts. These
    # requests only read persisted data and cannot start translation/provider work.
    with app.test_client() as client:
        paths = [f"/api/graph/data/{GRAPH_ID}?full=true",
                 f"/api/graph/data/{GRAPH_ID}?top_k=20&slim=true",
                 f"/api/graph/data/{GRAPH_ID}/node/browser-node-0000",
                 f"/api/graph/data/{GRAPH_ID}/edge/browser-edge-tail",
                 f"/api/graph/data/{GRAPH_ID}/neighbors/browser-node-0000"]
        paths += [f"/api/simulation/{sid}" for sid in IDS.values()]
        paths += [f"/api/simulation/{IDS['oasis']}/{suffix}" for suffix in (
            "profiles/realtime?platform=twitter", "profiles/realtime?platform=reddit",
            "posts?platform=twitter", "comments?platform=twitter", "posts?platform=reddit",
            "comments?platform=reddit", "feed-rounds?platform=twitter", "world-state", "run-status", "agent-stats")]
        paths += [f"/api/simulation/{IDS['world']}/world?view={view}{actor}" for view, actor in
                  (("public", ""), ("actor", "&actor_id=buyer"), ("analyst", ""))]
        paths += [f"/api/simulation/{IDS['record']}/record", f"/api/simulation/{IDS['record']}/record.md"]
        for path in paths:
            response = client.get(path)
            if response.status_code != 200:
                raise AssertionError(f"Fixture source read failed ({response.status_code}): {path}: {response.get_json()}")
            if path == paths[0]:
                graph = response.get_json()["data"]
    return {"graph": graph, "ids": dict(IDS)}


def test_install_simulations_authoritative_readers(tmp_path, monkeypatch):
    """Run this file explicitly under main_offline_pytest; no browser is required."""
    if "main_offline_guard" not in sys.modules:
        import pytest
        pytest.skip("Run this fixture through backend/scripts/main_offline_pytest.py")
    from app import create_app
    from app.api.simulation import simulation_translation_projection
    from app.services.artifact_translation import _graph_snapshot, _selected_pairs
    from app.services.simulation_record_contract import load_published_record

    app = create_app()
    installed = install_simulations(tmp_path, monkeypatch, app, model=None)
    assert installed["ids"] == IDS
    assert installed["graph"] == _graph()
    pairs, fingerprint, revision = _graph_snapshot(GRAPH_ID)
    assert len(pairs) == 1001 and len(fingerprint) == 64 and revision is None
    with app.test_client() as client:
        sid = IDS["oasis"]
        for platform in ("twitter", "reddit"):
            posts = client.get(f"/api/simulation/{sid}/posts?platform={platform}").json["data"]["posts"]
            comments = client.get(f"/api/simulation/{sid}/comments?platform={platform}").json["data"]["comments"]
            projection = simulation_translation_projection(sid, {"engine": "oasis-legacy", "platform": platform, "view": "public"})
            assert len(posts) == len(comments) == 2
            assert _selected_pairs([row["content"] for row in posts + comments], projection)
        world_state = client.get(f"/api/simulation/{sid}/world-state").json["data"]
        projection = simulation_translation_projection(sid, {"engine": "oasis-legacy", "platform": "",
            "view": "public", "round": 2, "revision": "2"})
        assert _selected_pairs([world_state["variables"][0]["provenance"]], projection)
        for view, actor in (("public", ""), ("actor", "buyer"), ("analyst", "")):
            response = client.get(f"/api/simulation/{IDS['world']}/world?view={view}" + (f"&actor_id={actor}" if actor else ""))
            data = response.json["data"]
            projection = simulation_translation_projection(IDS["world"], {"engine": "world-v1", "view": view,
                "actor_id": actor, "generation_id": data["generationId"], "revision": data["revision"], "round": data["round"]})
            assert projection["world"] == data
    record, status = load_published_record(str(tmp_path / "uploads" / "simulations" / IDS["record"]))
    assert status == "passed" and record["simulation_id"] == IDS["record"]
    revision = json.dumps([record.get(key) or "" for key in ("config_hash", "generator_version", "generated_at")], separators=(",", ":"))
    projection = simulation_translation_projection(IDS["record"], {"engine": "world-v1", "surface": "record", "view": "record",
        "round": record["periods"][0]["round"], "revision": revision, "platform": "", "actor_id": ""})
    assert _selected_pairs([record["banner"]], projection)
    # Exercise period-specific feed SQL after verifying every other authority.
    # The fixture adapter canonicalizes only the existing read-only URI spelling;
    # the original connection function, guard and SQL query stay active.
    with app.test_client() as client:
        for platform in ("twitter", "reddit"):
            for round_index in (1, 2):
                projection = simulation_translation_projection(IDS["oasis"], {"engine": "oasis-legacy", "platform": platform,
                    "round": round_index, "view": "public"})
                for kind in ("posts", "comments"):
                    selected = client.get(f"/api/simulation/{IDS['oasis']}/{kind}?platform={platform}&round={round_index}")
                    assert selected.status_code == 200, selected.json
                    assert _selected_pairs([row["content"] for row in selected.json["data"][kind]], projection)


def test_readonly_uri_adapter_keeps_guard_and_sqlite_readonly_enforcement(tmp_path, monkeypatch):
    if "main_offline_guard" not in sys.modules:
        import pytest
        pytest.skip("Run this fixture through backend/scripts/main_offline_pytest.py")
    import pytest

    guard = sys.modules["main_offline_guard"]
    sim_root = tmp_path / "uploads" / "simulations"
    database = sim_root / IDS["oasis"] / "twitter_simulation.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE marker (value TEXT)")
        db.execute("INSERT INTO marker VALUES ('source stays intact')")
    before = database.read_bytes()
    _install_readonly_uri_adapter(sim_root, monkeypatch)
    with sqlite3.connect("file:" + str(database) + "?mode=ro", uri=True) as db:
        assert db.execute("SELECT value FROM marker").fetchone()[0] == "source stays intact"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("INSERT INTO marker VALUES ('forbidden mutation')")
    assert database.read_bytes() == before
    # Every denied spelling reaches the ORIGINAL audit hook, never a silent
    # fallback to a normal writable connection or an in-memory database.
    saved = Path(__file__).resolve().parents[2] / "uploads" / "simulations" / "saved.db"
    invalid = [
        "file:" + str(saved) + "?mode=ro",
        "file:" + str(database) + "?mode=rw",
        "file:" + str(database) + "?mode=rwc",
        "file:" + str(database) + "?mode=ro&vfs=unix-none",
        "file:" + str(database) + "?mode=ro&immutable=1",
        "file:" + str(database) + "?mode=ro#fragment",
        "file://fixture.invalid" + str(database) + "?mode=ro",
    ]
    blocked_before = guard.counts["blocked:sqlite_uri"]
    for uri in invalid:
        with pytest.raises(PermissionError, match="main offline guard blocked sqlite_uri"):
            sqlite3.connect(uri, uri=True)
    assert guard.counts["blocked:sqlite_uri"] - blocked_before == len(invalid)
    assert database.read_bytes() == before
