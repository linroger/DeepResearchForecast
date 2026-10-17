"""world-v1 store: a new world appears atomically (persistence review, blocker B2).

Before: sqlite3.connect created an empty world.sqlite3 at once and the schema appeared only
when the init transaction committed, so the pipeline's one-second status poll could read a
half-made file (unsupported_store) and stop a healthy world, and a failed init left an
unusable empty file behind for good.  Pins: during initialisation the final path does not
exist (a reader gets missing_world, the "not started yet" answer); a failed initialisation
leaves neither the final file nor temporary files; a finished world opens read-only and the
writer runs it in WAL mode.
"""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.world_simulation import store as ws  # noqa: E402
from app.services.world_simulation.contracts import WorldError  # noqa: E402
from app.services.world_simulation.examples import example_spec  # noqa: E402


def test_reader_never_sees_a_half_made_world(tmp_path, monkeypatch):
    path = tmp_path / "sim_a" / "world.sqlite3"
    seen = {}
    original = ws.WorldStore._initialize

    def _observe(self, spec):
        seen["final_exists_during_init"] = path.exists()
        with pytest.raises(WorldError) as info:
            ws.WorldStore(path, read_only=True)
        seen["reader_code"] = info.value.code
        return original(self, spec)

    monkeypatch.setattr(ws.WorldStore, "_initialize", _observe)
    store = ws.WorldStore(path, spec=example_spec("investment"))
    store.close()
    assert seen == {"final_exists_during_init": False, "reader_code": "missing_world"}
    reader = ws.WorldStore(path, read_only=True)
    reader.close()
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
    assert [p.name for p in path.parent.iterdir() if p.name.startswith(".")] == []


def test_failed_initialisation_leaves_nothing_behind(tmp_path, monkeypatch):
    path = tmp_path / "sim_b" / "world.sqlite3"

    def _boom(self, spec):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ws.WorldStore, "_initialize", _boom)
    with pytest.raises(RuntimeError):
        ws.WorldStore(path, spec=example_spec("investment"))
    assert not path.exists()
    assert list(path.parent.iterdir()) == []
    # the next attempt starts cleanly
    monkeypatch.undo()
    ws.WorldStore(path, spec=example_spec("investment")).close()
    ws.WorldStore(path, read_only=True).close()



def test_a_concurrent_creator_never_replaces_a_published_world(tmp_path, monkeypatch):
    """While one creator initialises, a second publishes the same new world and opens it.  The
    first must not swap the file under that open connection (os.replace did); it opens the
    published world instead."""
    path = tmp_path / "sim_c" / "world.sqlite3"
    original = ws.WorldStore._initialize
    second = {}

    def _race(self, spec):
        if "store" not in second:
            second["store"] = None
            second["store"] = ws.WorldStore(path, spec=spec)
            second["inode"] = path.stat().st_ino
        return original(self, spec)

    monkeypatch.setattr(ws.WorldStore, "_initialize", _race)
    first = ws.WorldStore(path, spec=example_spec("investment"))
    try:
        assert path.stat().st_ino == second["inode"]
        assert first.head() == second["store"].head()
    finally:
        first.close()
        second["store"].close()
    assert [p.name for p in path.parent.iterdir() if p.name.startswith(".")] == []
