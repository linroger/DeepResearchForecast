"""Identifier containment and local API hardening (INFRA-10, candidate C38).

Report / project / simulation / pipeline / graph ids arrive from URLs, JSON bodies
and LLM tool calls and are joined into paths under ``uploads/`` (reports and
projects are then handed to ``shutil.rmtree``). Before this change
``DELETE /api/report/..`` resolved to ``REPORTS_DIR/..`` = ``uploads/`` and
rmtree'd every pipeline, simulation, report and graph. These tests pin:

- ``safe_id`` / ``contained_child``: the allow-list and the realpath containment;
- the sinks: ``delete_report`` / ``delete_project`` never rmtree outside their
  root, ``SimulationManager._get_simulation_dir`` never makedirs outside it, read
  getters map an unsafe id to "not found", directory scans skip stray entries,
  the simulation /posts and /comments views re-check ids and only accept the
  twitter/reddit databases;
- the regex fixes (pipeline ``\\Z`` and length cap, drf2 dot-only ids);
- the Flask id gate (404 for route ids, 400 for mutating JSON bodies);
- the DNS-rebinding Host allowlist on loopback trust (APP_HOST_CHECK, parsed
  fail-closed / APP_ALLOWED_HOSTS);
- ``_persist_env`` reporting failures and writing ``.env`` as 0600 through a
  git-ignored temp file.

Every test is offline and writes only under ``tmp_path``; the real repo-root
``.env`` is never touched (``_persist_env`` always gets an explicit tmp path).
"""

import asyncio
import os
import pathlib
import shutil
import stat
import sys
import types
import uuid

import pytest

# drf2 sits at the repo root (one level above backend/); conftest only adds backend/.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.config import Config  # noqa: E402
from app.utils.atomic import write_secret_text_atomic  # noqa: E402
from app.utils.security import UnsafeIdError, contained_child, is_safe_id, safe_id  # noqa: E402

# Captured at import time, before any autouse fixture can stub Config._persist_env
# for the duration of a test; called only with an explicit tmp env_path.
_REAL_PERSIST_ENV = Config.__dict__["_persist_env"].__get__(None, Config)


# ---------------------------------------------------------------- safe_id

GENERATED_IDS = [
    "report_ab12",
    "pipe_x-1",
    f"report_{uuid.uuid4().hex[:12]}",
    f"sim_{uuid.uuid4().hex[:12]}",
    f"proj_{uuid.uuid4().hex[:12]}",
    f"pipe_{uuid.uuid4().hex[:12]}",
    f"mirofish_{uuid.uuid4().hex[:16]}",
    uuid.uuid4().hex,
    str(uuid.uuid4()),  # task ids (TaskManager) are str(uuid4()) with hyphens
    "pipe_e2egold02",
    "a" * 128,
]

UNSAFE_IDS = [
    "..", ".", "...", "a/b", "a\\b", "x\n", "_x", "", "a" * 129, "a" * 200,
    "-x", "a.b", " x", "x ", "a\x00b", "a\tb", "../x", "..%2Fx", "report_1/..",
    None, 5, b"report_1", ["report_1"],
]


@pytest.mark.parametrize("value", GENERATED_IDS)
def test_safe_id_accepts_every_generated_id_format(value):
    assert safe_id(value, "test") == value
    assert is_safe_id(value) is True


@pytest.mark.parametrize("value", UNSAFE_IDS)
def test_safe_id_rejects_unsafe_values(value):
    with pytest.raises(UnsafeIdError):
        safe_id(value, "test")
    assert is_safe_id(value) is False


def test_unsafe_id_error_is_a_value_error_and_never_echoes_the_value():
    with pytest.raises(ValueError) as excinfo:
        safe_id("../../etc/passwd", "report")
    assert isinstance(excinfo.value, UnsafeIdError)
    assert str(excinfo.value) == "invalid report id"
    assert "etc" not in str(excinfo.value)


def test_safe_id_max_len_is_configurable():
    assert safe_id("a" * 64, "eval", max_len=64) == "a" * 64
    with pytest.raises(UnsafeIdError):
        safe_id("a" * 65, "eval", max_len=64)


# ---------------------------------------------------------------- contained_child

def test_contained_child_returns_the_unresolved_join(tmp_path):
    root = str(tmp_path / "reports")
    os.makedirs(root)
    assert contained_child(root, "report_ab12", "report") == os.path.join(root, "report_ab12")
    # A relative, un-normalised root keeps its exact spelling (byte-identical strings).
    odd_root = os.path.join(str(tmp_path), "x", "..", "reports")
    assert contained_child(odd_root, "report_ab12", "report") == os.path.join(odd_root, "report_ab12")


def test_contained_child_accepts_a_symlinked_root(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)
    assert contained_child(str(link_root), "sim_1", "simulation") == os.path.join(str(link_root), "sim_1")


def test_contained_child_rejects_a_symlink_escaping_the_root(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "report_evil").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafeIdError):
        contained_child(str(root), "report_evil", "report")


def test_contained_child_rejects_the_root_itself(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    (root / "report_self").symlink_to(root, target_is_directory=True)
    with pytest.raises(UnsafeIdError):
        contained_child(str(root), "report_self", "report")


@pytest.mark.parametrize("value", ["..", ".", "", "a/b", "../x"])
def test_contained_child_rejects_unsafe_ids(tmp_path, value):
    with pytest.raises(UnsafeIdError):
        contained_child(str(tmp_path), value, "report")


# ---------------------------------------------------------------- report sinks

@pytest.fixture
def reports_root(tmp_path, monkeypatch):
    from app.services.report_agent import ReportManager

    uploads = tmp_path / "uploads"
    reports = uploads / "reports"
    reports.mkdir(parents=True)
    # A sibling data tree that an escaped id would destroy.
    (uploads / "x").mkdir()
    (uploads / "x" / "keep.txt").write_text("keep", encoding="utf-8")
    (uploads / "pipelines").mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports))
    return reports


@pytest.fixture
def rmtree_calls(monkeypatch):
    calls = []
    real_rmtree = shutil.rmtree

    def recording_rmtree(path, *args, **kwargs):
        calls.append(os.fspath(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", recording_rmtree)
    return calls


@pytest.mark.parametrize("report_id", ["../x", "..", ".", "a/../..", "report_1\n"])
def test_delete_report_never_rmtrees_outside_reports_dir(reports_root, rmtree_calls, report_id):
    from app.services.report_agent import ReportManager

    with pytest.raises(UnsafeIdError):
        ReportManager.delete_report(report_id)
    assert rmtree_calls == []
    assert (reports_root.parent / "x" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (reports_root.parent / "pipelines").is_dir()


def _write_report_meta(folder, report_id, simulation_id="sim_1"):
    import json

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(json.dumps({
        "report_id": report_id,
        "simulation_id": simulation_id,
        "graph_id": "mirofish_0123456789abcdef",
        "simulation_requirement": "q",
        "status": "completed",
    }), encoding="utf-8")


def test_delete_report_still_deletes_a_valid_report(reports_root, rmtree_calls):
    from app.services.report_agent import ReportManager

    _write_report_meta(reports_root / "report_ab12", "report_ab12")
    assert ReportManager.delete_report("report_ab12") is True
    assert rmtree_calls == [os.path.join(str(reports_root), "report_ab12")]
    assert not (reports_root / "report_ab12").exists()


def test_delete_report_legacy_flat_files_still_work(reports_root, rmtree_calls):
    from app.services.report_agent import ReportManager

    (reports_root / "report_old.json").write_text("{}", encoding="utf-8")
    (reports_root / "report_old.md").write_text("# old", encoding="utf-8")
    assert ReportManager.delete_report("report_old") is True
    assert rmtree_calls == []
    assert not (reports_root / "report_old.json").exists()
    assert not (reports_root / "report_old.md").exists()


def test_report_folder_path_is_byte_identical_to_the_old_join(reports_root):
    from app.services.report_agent import ReportManager

    assert ReportManager._get_report_folder("report_ab12") == os.path.join(str(reports_root), "report_ab12")
    with pytest.raises(UnsafeIdError):
        ReportManager._get_report_folder("..")


@pytest.mark.parametrize("report_id", ["../x", "..", ".DS_Store", "_sim_index", "a/b"])
def test_report_read_getters_treat_unsafe_ids_as_not_found(reports_root, report_id):
    from app.services.report_agent import ReportManager

    assert ReportManager.get_report(report_id) is None
    assert ReportManager.load_structured_forecast(report_id) is None
    assert ReportManager.publication_status(report_id)["publishable"] is False
    assert ReportManager.is_publishable(report_id) is False


def test_report_listing_skips_stray_entries(reports_root):
    from app.services.report_agent import ReportManager

    _write_report_meta(reports_root / "report_ab12", "report_ab12", simulation_id="sim_1")
    (reports_root / ".DS_Store").write_bytes(b"\x00\x01")
    (reports_root / "_tmp").mkdir()
    (reports_root / ".hidden.json").write_text("{}", encoding="utf-8")
    (reports_root / "notes.bak.json").write_text("{}", encoding="utf-8")

    listed = ReportManager.list_reports()
    assert [r.report_id for r in listed] == ["report_ab12"]
    by_sim = ReportManager.get_report_by_simulation("sim_1")
    assert by_sim is not None and by_sim.report_id == "report_ab12"


# ---------------------------------------------------------------- project sinks

@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    from app.models.project import ProjectManager

    uploads = tmp_path / "uploads"
    projects = uploads / "projects"
    projects.mkdir(parents=True)
    (uploads / "x").mkdir()
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(projects))
    return projects


@pytest.mark.parametrize("project_id", ["..", "../x", ".", "a/b"])
def test_delete_project_never_rmtrees_outside_projects_dir(projects_root, rmtree_calls, project_id):
    from app.models.project import ProjectManager

    with pytest.raises(UnsafeIdError):
        ProjectManager.delete_project(project_id)
    assert rmtree_calls == []
    assert (projects_root.parent / "x").is_dir()


def test_project_lifecycle_and_listing_with_stray_entries(projects_root, rmtree_calls):
    from app.models.project import ProjectManager

    project = ProjectManager.create_project("demo")
    assert ProjectManager._get_project_dir(project.project_id) == os.path.join(
        str(projects_root), project.project_id
    )
    (projects_root / ".DS_Store").write_bytes(b"\x00")
    (projects_root / "_tmp").mkdir()

    assert [p.project_id for p in ProjectManager.list_projects()] == [project.project_id]
    assert ProjectManager.get_project("../x") is None
    assert ProjectManager.get_project(".DS_Store") is None
    assert ProjectManager.delete_project(project.project_id) is True
    assert rmtree_calls == [os.path.join(str(projects_root), project.project_id)]


# ---------------------------------------------------------------- simulation sinks

@pytest.fixture
def sims_root(tmp_path, monkeypatch):
    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner

    uploads = tmp_path / "uploads"
    sims = uploads / "simulations"
    sims.mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(sims))
    return sims


def _tree(path):
    return sorted(os.path.relpath(os.path.join(d, n), path)
                  for d, dirs, files in os.walk(path) for n in dirs + files)


@pytest.mark.parametrize("simulation_id", ["..", "../escape", "../../escape", "a/b", "."])
def test_get_simulation_dir_raises_before_creating_any_directory(sims_root, simulation_id):
    from app.services.simulation_manager import SimulationManager

    manager = SimulationManager()
    before = _tree(sims_root.parent.parent)
    with pytest.raises(UnsafeIdError):
        manager._get_simulation_dir(simulation_id)
    assert _tree(sims_root.parent.parent) == before
    assert manager._load_simulation_state(simulation_id) is None
    assert _tree(sims_root.parent.parent) == before


def test_get_simulation_dir_valid_id_unchanged(sims_root):
    from app.services.simulation_manager import SimulationManager

    sim_dir = SimulationManager()._get_simulation_dir("sim_0123456789ab")
    assert sim_dir == os.path.join(str(sims_root), "sim_0123456789ab")
    assert os.path.isdir(sim_dir)


def test_simulation_listing_skips_stray_entries(sims_root):
    from app.services.simulation_manager import SimulationManager

    (sims_root / ".DS_Store").write_bytes(b"\x00")
    (sims_root / "_zep_dead_letter").mkdir()
    (sims_root / "_sim_index.json").write_text("{}", encoding="utf-8")
    assert SimulationManager().list_simulations() == []


def test_simulation_runner_joins_go_through_contained_sim_dir(sims_root, rmtree_calls):
    from app.services.simulation_runner import SimulationRunner

    assert SimulationRunner._sim_dir("sim_1") == os.path.join(str(sims_root), "sim_1")
    for bad in ("..", "../x", "sim_1\n"):
        with pytest.raises(UnsafeIdError):
            SimulationRunner._sim_dir(bad)
        with pytest.raises(UnsafeIdError):
            SimulationRunner.cleanup_simulation_logs(bad)
        assert SimulationRunner._load_run_state(bad) is None
    assert rmtree_calls == []


def test_api_simulation_dir_helper_maps_unsafe_ids_to_missing(sims_root, monkeypatch):
    from app.api import simulation as sim_api

    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims_root))
    assert sim_api._simulation_dir_or_none("sim_1") == os.path.join(str(sims_root), "sim_1")
    assert sim_api._simulation_dir_or_none("..") is None
    ok, info = sim_api._check_simulation_prepared("../x")
    assert ok is False and info["reason"]


def _make_sim_db(path):
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE post (post_id INTEGER, content TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE comment (comment_id INTEGER, post_id INTEGER, content TEXT, created_at TEXT)")
    conn.execute("INSERT INTO post VALUES (1, 'hello', '2026-01-01')")
    conn.execute("INSERT INTO comment VALUES (7, 1, 'reply', '2026-01-02')")
    conn.commit()
    conn.close()


@pytest.fixture
def sim_db_client(app_client, sims_root, monkeypatch):
    """App client whose /posts and /comments endpoints read under ``sims_root``."""
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims_root))
    return app_client


def test_simulation_posts_and_comments_read_under_the_simulation_root(sim_db_client, sims_root):
    (sims_root / "sim_1").mkdir()
    _make_sim_db(sims_root / "sim_1" / "twitter_simulation.db")

    posts = sim_db_client.get("/api/simulation/sim_1/posts?platform=twitter").get_json()
    assert posts["success"] is True
    assert [p["content"] for p in posts["data"]["posts"]] == ["hello"]
    comments = sim_db_client.get("/api/simulation/sim_1/comments?platform=twitter").get_json()
    assert [c["content"] for c in comments["data"]["comments"]] == ["reply"]
    # No reddit database for this run: the unchanged "empty" answer.
    empty = sim_db_client.get("/api/simulation/sim_1/posts").get_json()
    assert empty["success"] is True and empty["data"]["posts"] == []


@pytest.mark.parametrize("endpoint", ["posts", "comments"])
@pytest.mark.parametrize("platform", ["../../outside/evil", "evil", "", "twitter/../x"])
def test_simulation_db_endpoints_reject_unknown_platforms(sim_db_client, sims_root, endpoint, platform):
    outside = sims_root.parent / "outside"
    outside.mkdir(exist_ok=True)
    _make_sim_db(outside / "evil_simulation.db")
    (sims_root / "sim_1").mkdir(exist_ok=True)
    _make_sim_db(sims_root / "sim_1" / "evil_simulation.db")

    resp = sim_db_client.get(f"/api/simulation/sim_1/{endpoint}", query_string={"platform": platform})
    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "platform 参数只能是 'twitter' 或 'reddit'"}


@pytest.mark.parametrize("view_name", ["get_simulation_posts", "get_simulation_comments"])
@pytest.mark.parametrize("simulation_id", ["..", "../outside", "a/b", "sim_1\n"])
def test_simulation_db_endpoints_contain_ids_without_the_gate(sim_db_client, sims_root, monkeypatch,
                                                                view_name, simulation_id):
    """The views re-check the id themselves (the Flask id gate is not their only guard)."""
    import sqlite3

    from app.api import simulation as sim_api

    _make_sim_db(sims_root.parent / "reddit_simulation.db")  # what "<root>/.." + db name would open
    outside = sims_root.parent / "outside"
    outside.mkdir()
    _make_sim_db(outside / "reddit_simulation.db")
    if simulation_id in ("..", "../outside"):  # a plain join would reach a real database
        assert os.path.isfile(os.path.join(str(sims_root), simulation_id, "reddit_simulation.db"))

    def _no_connect(*_a, **_k):
        raise AssertionError("an unsafe simulation id must never reach sqlite3.connect")

    monkeypatch.setattr(sqlite3, "connect", _no_connect)
    with sim_db_client.application.test_request_context("/?platform=reddit"):
        resp = getattr(sim_api, view_name)(simulation_id)
    payload = resp.get_json()
    assert payload["success"] is True
    assert payload["data"]["count"] == 0


# ---------------------------------------------------------------- MCP + graph paths

def test_mcp_sim_server_rejects_unsafe_sim_ids(sims_root):
    from app.mcp import sim_server

    assert sim_server._resolve_sim_id("sim_1") == "sim_1"
    assert sim_server._resolve_sim_id(" sim_1\n") == "sim_1"  # surrounding whitespace was always stripped
    for bad in ("..", "../x", "a/b", "a\nb"):
        with pytest.raises(UnsafeIdError):
            sim_server._resolve_sim_id(bad)
    for bad in ("..", "../x", "a/b", "x\n"):
        with pytest.raises(UnsafeIdError):
            sim_server._sim_dir(bad)
    assert sim_server._sim_dir("sim_1") == os.path.join(str(sims_root), "sim_1")


def test_mcp_kg_server_rejects_unsafe_graph_ids():
    from app.mcp import kg_server

    assert kg_server._resolve_graph_id("mirofish_0123456789abcdef") == "mirofish_0123456789abcdef"
    with pytest.raises(UnsafeIdError):
        kg_server._resolve_graph_id("../x")

    def _never_called(svc, graph_id):  # pragma: no cover - the id check fails first
        raise AssertionError("impl must not run for an unsafe graph_id")

    payload = asyncio.run(kg_server._guarded(_never_called, "../x"))
    assert payload["ok"] is False
    assert "UnsafeIdError" in payload["error"]


def test_graph_layout_path_is_contained(tmp_path, monkeypatch):
    from app.services import graph_builder

    monkeypatch.setattr(Config, "GRAPHITI_DATA_DIR", str(tmp_path))
    gid = "mirofish_0123456789abcdef"
    assert graph_builder.layout_positions_path(gid) == os.path.join(
        str(tmp_path), "layouts", gid, "positions.json"
    )
    with pytest.raises(UnsafeIdError):
        graph_builder.layout_positions_path("..")
    assert graph_builder.load_layout_positions("../x") == {}


def test_kuzu_graph_path_is_contained(tmp_path, monkeypatch):
    from app.services.graphiti_client.runtime import GraphitiRuntime

    class FakeKuzuDriver:
        def __init__(self, db):
            self.db = db

    fake_module = types.ModuleType("graphiti_core.driver.kuzu_driver")
    fake_module.KuzuDriver = FakeKuzuDriver
    monkeypatch.setitem(sys.modules, "graphiti_core.driver.kuzu_driver", fake_module)
    monkeypatch.setenv("GRAPHITI_DATA_DIR", str(tmp_path))
    runtime = GraphitiRuntime.__new__(GraphitiRuntime)  # no event-loop thread
    runtime._resolved_backend = "kuzu"

    driver = asyncio.run(runtime._make_driver("mirofish_0123456789abcdef"))
    assert driver.db == os.path.join(str(tmp_path), "kuzu", "mirofish_0123456789abcdef")
    with pytest.raises(UnsafeIdError):
        asyncio.run(runtime._make_driver("../x"))


# ---------------------------------------------------------------- regex fixes

def test_pipeline_id_regex_rejects_trailing_newline():
    from app.services.pipeline_orchestrator import PipelineManager

    assert PipelineManager._PIPELINE_ID_RE.fullmatch("pipe_x\n") is None
    assert PipelineManager._PIPELINE_ID_RE.match("pipe_x\n") is None
    for bad in ("pipe_x\n", "pipe_", "pipe_..", "pipe_a/b", "pipe_" + "a" * 129, None, 3):
        with pytest.raises(ValueError):
            PipelineManager._validate_id(bad)
    for good in ("pipe_e2egold02", f"pipe_{uuid.uuid4().hex[:12]}", "pipe_x-1"):
        assert PipelineManager._validate_id(good) == good
    assert PipelineManager.delete("pipe_x\n") is False


def test_pipeline_id_length_cap_matches_the_flask_id_gate():
    from app.services.pipeline_orchestrator import PipelineManager
    from app.utils.security import SAFE_ID_MAX_LEN

    longest = "pipe_" + "a" * (SAFE_ID_MAX_LEN - len("pipe_"))
    assert len(longest) == SAFE_ID_MAX_LEN
    assert PipelineManager._validate_id(longest) == longest
    assert is_safe_id(longest) is True
    too_long = longest + "a"
    with pytest.raises(ValueError):
        PipelineManager._validate_id(too_long)
    assert is_safe_id(too_long) is False


def test_drf2_state_store_rejects_dot_only_and_newline_ids(tmp_path):
    from drf2.driver.state import _ID_RE, StateStore

    assert _ID_RE.fullmatch("..") is not None  # the regex admits dots; the store rejects dot-only
    store = StateStore(str(tmp_path))
    for bad in ("..", ".", "...", "x\n", "", "a/b", None):
        with pytest.raises(ValueError):
            store.pipeline_dir(bad)
    assert _ID_RE.fullmatch("x\n") is None
    assert store.pipeline_dir("pipe.v2_1") == os.path.join(str(tmp_path), "pipe.v2_1")


# ---------------------------------------------------------------- Flask id gate

@pytest.fixture
def app_client(monkeypatch):
    from flask import jsonify, request

    from app import create_app

    monkeypatch.setattr(Config, "APP_API_TOKEN", "")
    monkeypatch.setattr(Config, "APP_HOST_CHECK", True)
    monkeypatch.setattr(Config, "APP_ALLOWED_HOSTS", "")
    app = create_app()
    app.config["TESTING"] = True

    def _probe(**view_args):
        return jsonify({"reached": True, "view_args": view_args,
                        "body": request.get_json(silent=True)})

    app.add_url_rule("/api/__id_probe__/<report_id>", "id_probe_report", _probe, methods=["GET", "DELETE"])
    app.add_url_rule("/api/__id_probe__", "id_probe_body", _probe, methods=["GET", "POST", "PUT"])
    return app.test_client()


@pytest.fixture
def report_views_must_not_run(monkeypatch):
    from app.services.report_agent import ReportManager

    def _boom(*_a, **_k):
        raise AssertionError("the view must not run for an unsafe id")

    for name in ("get_report", "delete_report", "_get_report_folder"):
        monkeypatch.setattr(ReportManager, name, classmethod(_boom))


@pytest.mark.parametrize("path", [
    "/api/report/..%2F..%2Fetc",
    "/api/report/..",
    "/api/report/%2E%2E",
    "/api/report/_sim_index",
])
def test_route_ids_that_are_unsafe_get_404(app_client, report_views_must_not_run, path):
    assert app_client.get(path).status_code == 404
    # A decoded '/' splits the id into several segments that no report route accepts
    # (only the GET-only SPA catch-all does, hence 405 for DELETE); a single-segment
    # id reaches the id gate. Either way no report view runs.
    assert app_client.delete(path).status_code in ((404, 405) if "%2F" in path else (404,))


def test_delete_report_dot_dot_over_http_never_rmtrees(app_client, reports_root, rmtree_calls):
    resp = app_client.delete("/api/report/..")
    assert resp.status_code == 404
    assert resp.get_json() == {"success": False, "error": "not found"}  # the id gate, not the router
    assert rmtree_calls == []
    assert (reports_root.parent / "x" / "keep.txt").exists()


def test_route_id_gate_passes_valid_ids(app_client):
    resp = app_client.get("/api/__id_probe__/report_ab12")
    assert resp.status_code == 200
    assert resp.get_json()["view_args"] == {"report_id": "report_ab12"}
    blocked = app_client.get("/api/__id_probe__/_x")
    assert blocked.status_code == 404
    assert "_x" not in blocked.get_data(as_text=True)


def test_mutating_json_body_with_unsafe_id_gets_400(app_client):
    resp = app_client.post("/api/report/generate", json={"simulation_id": "../x"})
    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "invalid simulation_id"}
    for key in ("report_id", "project_id", "pipeline_id", "graph_id", "task_id"):
        resp = app_client.post("/api/__id_probe__", json={key: ".."})
        assert resp.status_code == 400, key
    assert app_client.put("/api/__id_probe__", json={"simulation_id": 5}).status_code == 400
    assert app_client.post("/api/__id_probe__", json={"simulation_id": ["sim_1"]}).status_code == 400


def test_json_body_gate_skips_missing_empty_and_non_mutating(app_client):
    for body in ({}, {"simulation_id": None}, {"simulation_id": ""}, {"simulation_id": "sim_1"},
                 {"other_id": "../x"}, ["../x"], {"nested": {"simulation_id": "../x"}}):
        resp = app_client.post("/api/__id_probe__", json=body)
        assert resp.status_code == 200, body
        assert resp.get_json()["reached"] is True
    # GET bodies are not mutating requests: left to the view.
    assert app_client.get("/api/__id_probe__", json={"simulation_id": "../x"}).status_code == 200
    # A malformed JSON body is left to the endpoint's own parsing.
    resp = app_client.post("/api/__id_probe__", data="{not json", content_type="application/json")
    assert resp.status_code == 200


def test_endpoint_missing_id_error_is_preserved(app_client):
    resp = app_client.post("/api/report/generate", json={"simulation_id": ""})
    assert resp.status_code == 400
    assert resp.get_json()["error"] != "invalid simulation_id"


# ---------------------------------------------------------------- Host allowlist

PROBE = "/api/__host_probe__"  # unknown /api route: passes the gate -> 404, blocked -> 401/403


def _host_get(client, host, remote="127.0.0.1", headers=None):
    return client.get(PROBE, headers={"Host": host, **(headers or {})},
                      environ_base={"REMOTE_ADDR": remote})


@pytest.mark.parametrize("host", [
    "localhost", "localhost:5001", "127.0.0.1", "127.0.0.1:5001", "[::1]:5001", "LOCALHOST:3000",
])
def test_loopback_with_local_host_header_is_trusted(app_client, host):
    assert _host_get(app_client, host).status_code == 404


@pytest.mark.parametrize("host", ["evil.example", "evil.example:5001", "localhost.evil.example",
                                  "127.0.0.1.nip.io", "drf.test"])
def test_loopback_with_foreign_host_header_is_forbidden(app_client, host):
    resp = _host_get(app_client, host)
    assert resp.status_code == 403
    assert "APP_ALLOWED_HOSTS" in resp.get_json()["error"]


def test_app_allowed_hosts_extends_the_allowlist(app_client, monkeypatch):
    monkeypatch.setattr(Config, "APP_ALLOWED_HOSTS", " drf.test , other.test:9000 ")
    assert _host_get(app_client, "drf.test").status_code == 404
    assert _host_get(app_client, "DRF.test:5001").status_code == 404
    assert _host_get(app_client, "other.test").status_code == 404
    assert _host_get(app_client, "evil.example").status_code == 403


def test_app_host_check_false_restores_legacy_loopback_trust(app_client, monkeypatch):
    monkeypatch.setattr(Config, "APP_HOST_CHECK", False)
    assert _host_get(app_client, "evil.example").status_code == 404


def test_token_authenticated_requests_are_unaffected_by_host(app_client, monkeypatch):
    monkeypatch.setattr(Config, "APP_API_TOKEN", "s3cret")
    assert _host_get(app_client, "evil.example").status_code == 401
    assert _host_get(app_client, "evil.example", headers={"X-API-Token": "s3cret"}).status_code == 404
    assert _host_get(app_client, "evil.example", remote="192.0.2.9",
                     headers={"X-API-Token": "s3cret"}).status_code == 404


def test_host_check_does_not_gate_non_api_paths(app_client):
    resp = app_client.get("/health", headers={"Host": "evil.example"})
    assert resp.status_code == 200


def test_host_header_parsing():
    from app import _is_local_host_header

    assert _is_local_host_header("localhost:5001") is True
    assert _is_local_host_header("[::1]") is True
    assert _is_local_host_header("::1") is True
    assert _is_local_host_header("") is False
    assert _is_local_host_header(None) is False
    assert _is_local_host_header("evil.example", ",, ") is False
    assert _is_local_host_header("drf.test:80", "drf.test") is True


def test_host_check_knobs_default_on_and_are_documented():
    import re

    repo = pathlib.Path(_REPO_ROOT)
    config_src = (repo / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    assert "os.environ.get('APP_HOST_CHECK', 'true')" in config_src
    assert "os.environ.get('APP_ALLOWED_HOSTS', '')" in config_src
    example = (repo / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^# APP_HOST_CHECK=true\s", example, re.M)
    assert re.search(r"^# APP_ALLOWED_HOSTS=\s", example, re.M)


def _fresh_config_class(monkeypatch, **env):
    """Evaluate a private copy of app/config.py under *env* (None = unset).

    DRF_TEST_PROCESS=1 keeps the copy from loading the developer ``.env``; the shared
    ``app.config.Config`` is untouched.
    """
    import importlib.util

    monkeypatch.setenv("DRF_TEST_PROCESS", "1")
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    path = pathlib.Path(_REPO_ROOT) / "backend" / "app" / "config.py"
    spec = importlib.util.spec_from_file_location("_infra10_config_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Config


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
    ("", True), ("ture", True),
    ("false", False), ("FALSE", False), (" False ", False), ("0", False), ("no", False), ("off", False),
])
def test_app_host_check_parse_fails_closed(monkeypatch, raw, expected):
    assert _fresh_config_class(monkeypatch, APP_HOST_CHECK=raw).APP_HOST_CHECK is expected


# ---------------------------------------------------------------- .env persistence

def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_persist_env_writes_owner_only_file_and_upserts(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\nLLM_PROVIDER=openai\nKEEP=1\n", encoding="utf-8")
    os.chmod(env_path, 0o644)
    old_umask = os.umask(0o002)
    try:
        ok = _REAL_PERSIST_ENV({"LLM_PROVIDER": "claude-cli", "NEW_KEY": "v"}, env_path=str(env_path))
    finally:
        os.umask(old_umask)
    assert ok == (True, None)
    assert _mode(env_path) == 0o600
    assert env_path.read_text(encoding="utf-8") == "# comment\nLLM_PROVIDER=claude-cli\nKEEP=1\nNEW_KEY=v\n"
    assert sorted(os.listdir(tmp_path)) == [".env"]


def test_persist_env_on_read_only_dir_reports_permission_error(tmp_path):
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    env_path = ro_dir / ".env"
    env_path.write_text("KEEP=1\n", encoding="utf-8")
    os.chmod(ro_dir, 0o500)
    try:
        if os.access(ro_dir, os.W_OK):  # pragma: no cover - running as root
            pytest.skip("directory permissions are not enforced for this user")
        assert _REAL_PERSIST_ENV({"LLM_PROVIDER": "x"}, env_path=str(env_path)) == (False, "PermissionError")
        assert env_path.read_text(encoding="utf-8") == "KEEP=1\n"
        assert sorted(os.listdir(ro_dir)) == [".env"]
    finally:
        os.chmod(ro_dir, 0o700)


def test_persist_env_rejects_injection_without_writing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP=1\n", encoding="utf-8")
    assert _REAL_PERSIST_ENV({"LLM_API_KEY": "sk\nEVIL=1"}, env_path=str(env_path)) == (False, "ValueError")
    assert env_path.read_text(encoding="utf-8") == "KEEP=1\n"


def test_write_secret_text_atomic_mode_and_cleanup(tmp_path, monkeypatch):
    target = tmp_path / "sub" / "secret.env"
    write_secret_text_atomic(str(target), "A=1\n")
    assert target.read_text(encoding="utf-8") == "A=1\n"
    assert _mode(target) == 0o600

    def failing_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        write_secret_text_atomic(str(target), "A=2\n")
    assert target.read_text(encoding="utf-8") == "A=1\n"
    assert sorted(os.listdir(target.parent)) == ["secret.env"]


def test_secret_temp_file_name_is_git_ignored_next_to_the_repo_env(tmp_path, monkeypatch):
    """A SIGKILL between create and rename leaves the 0600 temp copy of .env behind;
    the repo's ignore rules must keep ``git add .`` from committing it."""
    import subprocess

    if shutil.which("git") is None or not os.path.exists(os.path.join(_REPO_ROOT, ".git")):
        pytest.skip("needs git and a git checkout of the repo")
    temp_names = []
    real_replace = os.replace

    def recording_replace(src, dst):
        temp_names.append(os.path.basename(src))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", recording_replace)
    write_secret_text_atomic(str(tmp_path / ".env"), "A=1\n")
    assert len(temp_names) == 1
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", temp_names[0]],
        cwd=_REPO_ROOT, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, f"{temp_names[0]!r} is not git-ignored at the repo root"


@pytest.fixture
def provider_sandbox(monkeypatch):
    """Snapshot every Config attribute / env var apply_provider mutates."""
    for attr in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_API_KEY", "DEERFLOW_MODEL",
                 "_is_kimi", "_is_minimax", "_is_deepseek", "_is_qwen", "_is_glm"):
        monkeypatch.setattr(Config, attr, getattr(Config, attr))
    for key in ("LLM_PROVIDER", "DEERFLOW_MODEL"):
        monkeypatch.setenv(key, "")  # records the original value so apply_provider's writes are undone
        monkeypatch.delenv(key)
    return monkeypatch


def test_apply_provider_reports_env_persistence(provider_sandbox, tmp_path):
    env_path = tmp_path / ".env"
    provider_sandbox.setattr(Config, "_persist_env", classmethod(
        lambda cls, updates, **_: _REAL_PERSIST_ENV(updates, env_path=str(env_path))))
    info = Config.apply_provider("claude-cli")
    assert info["env_persisted"] is True
    assert info["env_persist_error"] is None
    assert info["current"] == "claude-cli"
    assert _mode(env_path) == 0o600
    assert "LLM_PROVIDER=claude-cli" in env_path.read_text(encoding="utf-8")

    provider_sandbox.setattr(Config, "_persist_env", classmethod(
        lambda cls, updates, **_: (False, "PermissionError")))
    info = Config.apply_provider("claude-cli")
    assert info["env_persisted"] is False
    assert info["env_persist_error"] == "PermissionError"
    assert Config.LLM_PROVIDER == "claude-cli"  # the runtime switch still applied


def test_apply_provider_tolerates_legacy_none_returning_stub(provider_sandbox):
    provider_sandbox.setattr(Config, "_persist_env", classmethod(lambda cls, updates, *a, **k: None))
    info = Config.apply_provider("claude-cli")
    assert info["env_persisted"] is True
    assert info["env_persist_error"] is None


def test_settings_api_surfaces_env_persistence(provider_sandbox):
    from app import create_app

    provider_sandbox.setattr(Config, "APP_API_TOKEN", "")
    provider_sandbox.setattr(Config, "_persist_env", classmethod(
        lambda cls, updates, **_: (False, "PermissionError")))
    client = create_app().test_client()
    resp = client.post("/api/settings/llm", json={"provider": "claude-cli"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["env_persisted"] is False
    assert data["env_persist_error"] == "PermissionError"
