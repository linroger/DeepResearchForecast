"""Real persistence → research promotion/finalization → official-data consumer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from app.services import pipeline_orchestrator as po
from app.services.official_data import data_api, load_official_data


def _bind_sources():
    guard = sys.modules.get("main_offline_guard")
    if guard:
        for module in (po, data_api(), sys.modules["app.services.official_data"]):
            path = Path(module.__file__).resolve()
            guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()


_bind_sources()


def _generation(root, value=4.2, *, page=False):
    api = data_api()
    root.mkdir(parents=True, exist_ok=True)
    (root / "research_report.md").write_text("# Evidence\n" + "bounded official observations " * 40)
    series = api.Series(series="fred:UNRATE", provider="fred", title="Unemployment",
                        units="Percent", frequency="M", seasonal_adjustment="SA",
                        geography="USA", source_url="https://fred.stlouisfed.org/series/UNRATE",
                        retrieved_at="2026-10-12T00:00:00Z", route="fixture",
                        provenance={"receipt": "offline-original"},
                        observations=[api.Observation("2024-01-01", value), api.Observation("2024-02-01", None)])
    manifest = api.write_dataset_files([series], root, citations={series.series: "S1"})
    assert "error" not in manifest
    row = manifest["series"][0]
    if page:
        folder = root / "data/candidates"
        folder.mkdir(exist_ok=True)
        raw = json.dumps(series.to_dict(), ensure_ascii=False, sort_keys=True).encode()
        content = api.render_series_page(series).encode()
        (folder / "current.json").write_bytes(raw)
        (folder / "current.txt").write_bytes(content)
        (root / "sources.json").write_text(json.dumps([{
            "source_origin": "official_data", "content": content.decode(),
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "dataset": {"series": series.series, "snapshot": series.to_dict(),
                        "file": "data/candidates/current.json", "page": "data/candidates/current.txt"},
        }]))
    return manifest, row


def _bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_promoted_data_reaches_real_consumer_and_seal(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    _, row = _generation(source, page=True)
    expected = load_official_data(source)
    original = _bytes(source)
    (source / "data/unrelated-old.json").write_text("stale")
    seal = po._promote_research_contract(str(source), str(target))
    assert po._validate_research_contract(str(target))
    assert load_official_data(target) == expected
    for rel, raw in original.items():
        assert (target / rel).read_bytes() == raw
        assert seal["files"][rel] == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert not (target / "data/unrelated-old.json").exists()
    assert row["file"] in seal["files"]


def test_finalization_preserves_data_bytes_and_noop_generation(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(source, page=True)
    po._promote_research_contract(str(source), str(target))
    expected = load_official_data(source)
    data = _bytes(source / "data")
    payload = {"report": "# Finalized\n" + "sanctioned evidence " * 40}
    final = po._finalize_research_contract(str(target), payload)
    assert load_official_data(target) == expected
    assert _bytes(target / "data") == data
    assert po._validate_research_contract(str(target))
    assert po._finalize_research_contract(str(target), payload) == final


@pytest.mark.parametrize("damage", ["missing", "tamper", "hash", "metadata", "duplicate", "bad_row", "page"])
def test_invalid_source_is_not_partially_promoted_and_preserves_target(tmp_path, damage):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(target, 3.0)
    po._promote_research_contract(str(target), str(target))
    before = _bytes(target)
    manifest, row = _generation(source, page=True)
    if damage == "missing":
        (source / row["csv"]).unlink()
    elif damage == "tamper":
        (source / row["file"]).write_text("{}")
    elif damage == "hash":
        row["csv_sha256"] = "0" * 64
    elif damage == "metadata":
        row["units"] = "Wrong"
    elif damage == "duplicate":
        manifest["series"].append(dict(row))
    elif damage == "bad_row":
        manifest["series"].append({"series": "fred:CPIAUCSL", "file": "data/missing.json"})
    else:
        (source / "data/candidates/current.txt").write_text("corrupt page")
    (source / "data/datasets.json").write_text(json.dumps(manifest))
    with pytest.raises((RuntimeError, ValueError, OSError)):
        po._promote_research_contract(str(source), str(target))
    assert _bytes(target) == before
    assert po._validate_research_contract(str(target))
    assert load_official_data(target) is not None


@pytest.mark.parametrize("damage", ["missing", "tamper", "unsealed", "extra", "link"])
def test_seal_rejects_data_damage(tmp_path, damage):
    source, target = tmp_path / "source", tmp_path / "target"
    _, row = _generation(source)
    po._promote_research_contract(str(source), str(target))
    # On the old implementation, supply the lost files to expose the seal gap.
    if not (target / "data").exists():
        import shutil
        shutil.copytree(source / "data", target / "data")
    path = target / row["file"]
    if damage == "missing":
        path.unlink()
    elif damage == "tamper":
        path.write_bytes(path.read_bytes() + b" ")
    elif damage == "extra":
        (target / "data/old.json").write_text("stale")
    elif damage == "link":
        raw = path.read_bytes()
        path.unlink()
        sibling = tmp_path / "linked.json"
        sibling.write_bytes(raw)
        path.symlink_to(sibling)
    else:
        seal_path = target / po._RESEARCH_CONTRACT_FILENAME
        seal = json.loads(seal_path.read_text())
        seal["files"] = {k: v for k, v in seal["files"].items() if not k.startswith("data/")}
        seal_path.write_text(json.dumps(seal))
    assert not po._validate_research_contract(str(target))
    with pytest.raises(RuntimeError):
        po._finalize_research_contract(str(target), {"report": "new evidence " * 60})


@pytest.mark.parametrize("phase", ["install", "seal"])
def test_failure_restores_previous_valid_data(tmp_path, monkeypatch, phase):
    source, previous, target = tmp_path / "source", tmp_path / "previous", tmp_path / "target"
    _generation(previous, 3.0, page=True)
    _generation(source, 8.0)
    po._promote_research_contract(str(previous), str(target))
    before, expected = _bytes(target), load_official_data(previous)
    if phase == "install":
        replace = po.os.replace
        def fail(src, dst, *args, **kwargs):
            if ".research-stage-" in str(src) and Path(dst) == target / "data":
                raise OSError("injected data install failure")
            return replace(src, dst, *args, **kwargs)
        monkeypatch.setattr(po.os, "replace", fail)
    else:
        from app.utils import atomic
        write = atomic.write_json_atomic
        def fail(path, value, *args, **kwargs):
            if Path(path) == target / po._RESEARCH_CONTRACT_FILENAME:
                raise OSError("injected seal failure")
            return write(path, value, *args, **kwargs)
        monkeypatch.setattr(atomic, "write_json_atomic", fail)
    with pytest.raises(OSError, match="injected"):
        po._promote_research_contract(str(source), str(target))
    assert _bytes(target) == before
    assert load_official_data(target) == expected
    assert po._validate_research_contract(str(target))
    assert not list(target.glob(".research-*"))


def test_source_without_data_removes_stale_target_data(tmp_path):
    previous, target, source = tmp_path / "previous", tmp_path / "target", tmp_path / "source"
    _generation(previous)
    po._promote_research_contract(str(previous), str(target))
    # Install stale data explicitly so the old implementation exposes its leak.
    if not (target / "data").exists():
        import shutil
        shutil.copytree(previous / "data", target / "data")
    source.mkdir()
    (source / "research_report.md").write_text("no official datasets " * 40)
    po._promote_research_contract(str(source), str(target))
    assert not (target / "data").exists()
    assert load_official_data(target) is None
    assert po._validate_research_contract(str(target))


@pytest.mark.parametrize("kind", ["directory", "manifest", "json", "csv", "page"])
def test_source_symlinks_refused(tmp_path, kind):
    source, target = tmp_path / "source", tmp_path / "target"
    _, row = _generation(source, page=True)
    relative = {"directory": "data", "manifest": "data/datasets.json", "json": row["file"],
                "csv": row["csv"], "page": "data/candidates/current.txt"}[kind]
    path = source / relative
    real = tmp_path / "link-target"
    path.rename(real)
    path.symlink_to(real, target_is_directory=kind == "directory")
    with pytest.raises((RuntimeError, ValueError, OSError)):
        po._promote_research_contract(str(source), str(target))
    assert not (target / po._RESEARCH_CONTRACT_FILENAME).exists()


def test_new_generation_removes_old_files_without_rewriting_source(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    first, _ = _generation(source, 3.0)
    po._promote_research_contract(str(source), str(target))
    _generation(source, 8.0)
    before = _bytes(source)
    current = json.loads((source / "data/datasets.json").read_text())["series"][0]
    seal = po._promote_research_contract(str(source), str(target))
    assert load_official_data(target) == load_official_data(source)
    assert _bytes(source) == before
    assert not (target / first["series"][0]["file"]).exists()
    assert {p for p in seal["files"] if p.startswith("data/")} == {
        "data/datasets.json", current["file"], current["csv"]}


@pytest.mark.parametrize("kind", ["manifest_bytes", "file_bytes", "page_bytes", "total_bytes", "series_count"])
def test_bounds_reject_before_replacing_target(tmp_path, monkeypatch, kind):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(target, 3.0)
    po._promote_research_contract(str(target), str(target))
    before = _bytes(target)
    manifest, row = _generation(source, page=True)
    if kind == "manifest_bytes":
        (source / "data/datasets.json").write_bytes(b" " * (po._RESEARCH_DATA_FILE_LIMIT + 1))
    elif kind == "file_bytes":
        (source / row["file"]).write_bytes(b" " * (po._RESEARCH_DATA_FILE_LIMIT + 1))
    elif kind == "page_bytes":
        (source / "data/candidates/current.txt").write_bytes(b" " * 48001)
    elif kind == "total_bytes":
        monkeypatch.setattr(po, "_RESEARCH_DATA_TOTAL_LIMIT", 100)
    else:
        manifest["series"] = [row] * 201
        (source / "data/datasets.json").write_text(json.dumps(manifest))
    with pytest.raises((ValueError, RuntimeError, OSError)):
        po._promote_research_contract(str(source), str(target))
    assert _bytes(target) == before


def test_finalization_failure_restores_data_and_seal(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(source, page=True)
    po._promote_research_contract(str(source), str(target))
    before = _bytes(target)
    from app.utils import atomic
    write = atomic.write_json_atomic
    def fail(path, value, *args, **kwargs):
        if Path(path) == target / po._RESEARCH_CONTRACT_FILENAME:
            raise OSError("injected finalization seal failure")
        return write(path, value, *args, **kwargs)
    monkeypatch.setattr(atomic, "write_json_atomic", fail)
    with pytest.raises(OSError, match="injected"):
        po._finalize_research_contract(str(target), {"report": "final evidence " * 60})
    assert _bytes(target) == before
    assert load_official_data(target) == load_official_data(source)
    assert po._validate_research_contract(str(target))
    assert not list(target.glob(".research-*"))


def test_initial_manifest_move_failure_preserves_prior_seal(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(target, 3.0)
    po._promote_research_contract(str(target), str(target))
    _generation(source, 8.0)
    before = _bytes(target)
    replace = po.os.replace
    def fail(src, dst, *args, **kwargs):
        if Path(src) == target / po._RESEARCH_CONTRACT_FILENAME:
            raise OSError("injected initial seal move failure")
        return replace(src, dst, *args, **kwargs)
    monkeypatch.setattr(po.os, "replace", fail)
    with pytest.raises(OSError, match="injected"):
        po._promote_research_contract(str(source), str(target))
    assert _bytes(target) == before
    assert po._validate_research_contract(str(target))


@pytest.mark.parametrize("reference", ["../escaped.txt", "/absolute.txt", "data/../escaped.txt"])
def test_unsupported_page_path_fails_without_publishing_dangling_reference(tmp_path, reference):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(source, page=True)
    sources = json.loads((source / "sources.json").read_text())
    sources[0]["dataset"]["page"] = reference
    (source / "sources.json").write_text(json.dumps(sources))
    with pytest.raises((ValueError, RuntimeError, OSError)):
        po._promote_research_contract(str(source), str(target))
    assert not (target / po._RESEARCH_CONTRACT_FILENAME).exists()


def test_missing_entire_data_tree_cannot_publish_source_page_references(tmp_path):
    import shutil
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(source, page=True)
    shutil.rmtree(source / "data")
    with pytest.raises(ValueError, match="references missing data"):
        po._promote_research_contract(str(source), str(target))
    assert not (target / po._RESEARCH_CONTRACT_FILENAME).exists()


def test_empty_dataset_manifest_is_preserved_and_unreferenced_files_omitted(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(source)
    (source / "data/datasets.json").write_text('{"schema_version": 1, "series": []}')
    raw = (source / "data/datasets.json").read_bytes()
    po._promote_research_contract(str(source), str(target))
    assert _bytes(target / "data") == {"datasets.json": raw}
    assert load_official_data(target) is None
    assert po._validate_research_contract(str(target))


def test_restoration_failure_retains_recoverable_prior_generation(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(target, 3.0, page=True)
    po._promote_research_contract(str(target), str(target))
    prior = _bytes(target)
    _generation(source, 8.0)
    from app.utils import atomic
    write = atomic.write_json_atomic
    replace = po.os.replace
    def fail_seal(path, value, *args, **kwargs):
        if Path(path) == target / po._RESEARCH_CONTRACT_FILENAME:
            raise OSError("injected seal failure")
        return write(path, value, *args, **kwargs)
    def fail_restore(src, dst, *args, **kwargs):
        if ".research-rollback-" in str(src) and Path(dst) == target / "data":
            raise OSError("injected restore failure")
        return replace(src, dst, *args, **kwargs)
    monkeypatch.setattr(atomic, "write_json_atomic", fail_seal)
    monkeypatch.setattr(po.os, "replace", fail_restore)
    with pytest.raises(RuntimeError, match="recovery artifacts retained") as error:
        po._promote_research_contract(str(source), str(target))
    backups = list(target.glob(".research-rollback-*"))
    assert len(backups) == 1 and str(backups[0]) in str(error.value)
    # Restored files plus retained backup still contain every original byte.
    for relative, raw in prior.items():
        backup = backups[0] / relative
        assert (backup if backup.exists() else target / relative).read_bytes() == raw
    assert not po._validate_research_contract(str(target))
    monkeypatch.setattr(po.os, "replace", replace)
    for path in list(backups[0].iterdir()):
        replace(path, target / path.name)
    backups[0].rmdir()
    assert _bytes(target) == prior
    assert po._validate_research_contract(str(target))
    assert load_official_data(target)["series"][0]["observations"][0]["value"] == 3.0


@pytest.mark.parametrize("ancestor", [False, True])
def test_destination_alias_refused_before_mutation(tmp_path, ancestor):
    source, real = tmp_path / "source", tmp_path / "real"
    _generation(source)
    _generation(real, 3.0)
    po._promote_research_contract(str(real), str(real))
    before = _bytes(real)
    if ancestor:
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        target = alias / "real"
    else:
        target = tmp_path / "alias"
        target.symlink_to(real, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        po._promote_research_contract(str(source), str(target))
    assert _bytes(real) == before
    assert not po._validate_research_contract(str(target))
    with pytest.raises((ValueError, OSError)):
        po._finalize_research_contract(str(target), {"report": "changed evidence " * 60})
    assert _bytes(real) == before


def test_data_enumeration_stops_at_entry_limit(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    consumed = 0
    class Entry:
        name = "stale.json"
        def is_symlink(self):
            return False
        def is_dir(self, **kwargs):
            return False
        def is_file(self, **kwargs):
            return True
    class Entries:
        def __iter__(self):
            return self
        def __next__(self):
            nonlocal consumed
            consumed += 1
            assert consumed <= 1001, "enumeration read beyond its bound"
            return Entry()
        def close(self):
            pass
    with monkeypatch.context() as patch:
        patch.setattr(po.os, "scandir", lambda directory: Entries())
        with pytest.raises(ValueError, match="entry limit"):
            po._research_data_file_set(str(root))
    assert consumed == 1001


def test_partial_consumer_success_cannot_seal_a_corrupt_manifest_row(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(source)
    api = data_api()
    first = api.load_datasets(source)[0]
    second = api.Series.from_dict({**first, "series": "fred:CPIAUCSL", "units": "Index"})
    manifest = api.write_dataset_files([second], source, citations={second.series: "S2"})
    assert len(api.load_datasets(source)) == 2
    manifest["series"][1]["units"] = "corrupt metadata"
    (source / "data/datasets.json").write_text(json.dumps(manifest))
    assert len(api.load_datasets(source)) == 1  # The public consumer tolerates this partial failure.
    with pytest.raises(ValueError, match="unavailable rows"):
        po._promote_research_contract(str(source), str(target))
    assert not (target / po._RESEARCH_CONTRACT_FILENAME).exists()


def test_parent_traversal_cannot_hide_a_root_symlink(tmp_path):
    source, base, elsewhere = tmp_path / "source", tmp_path / "base", tmp_path / "elsewhere"
    _generation(source)
    base.mkdir()
    (elsewhere / "nested").mkdir(parents=True)
    real = elsewhere / "target"
    _generation(real, 3.0)
    po._promote_research_contract(str(real), str(real))
    before = _bytes(real)
    (base / "link").symlink_to(elsewhere / "nested", target_is_directory=True)
    supplied = str(base) + "/link/../target"
    with pytest.raises(ValueError, match="parent traversal"):
        po._promote_research_contract(str(source), supplied)
    assert not (base / "target").exists()
    assert _bytes(real) == before
    assert not po._validate_research_contract(supplied)
    with pytest.raises(ValueError, match="parent traversal"):
        po._finalize_research_contract(supplied, {"report": "final evidence " * 60})
    assert not (base / "target").exists()
    assert _bytes(real) == before


def test_non_global_track_merge_publishes_the_union_of_lane_datasets(tmp_path):
    """L10 (orchestrator part): lanes merged without global synthesis keep their official
    data. Validated lane generations are copied byte for byte, one manifest keeps the
    first lane's row per series with the merged [S#], a lane page that collides with
    another lane's bytes loses only its dataset reference, and a damaged lane degrades."""
    from official_data_replay import publish, replay
    handoff = tmp_path / "handoff"
    first, second, third, broken = (handoff / f"track_{k}" for k in range(4))
    _generation(first, 4.2, page=True)
    _generation(second, 5.1, page=True)  # same candidate paths, different bytes
    dgs10 = replay("fred_dgs10_daily", tmp_path)
    publish([dgs10], third)
    row = json.loads((third / "data/datasets.json").read_text())["series"][0]
    (third / "sources.json").write_text(json.dumps([{
        "url": "https://fred.stlouisfed.org/series/DGS10", "source_origin": "official_data",
        "dataset": {"series": "fred:DGS10", "file": row["file"]}}]))
    broken.mkdir(parents=True)
    (broken / "sources.json").write_text(json.dumps([{"dataset": {"series": "fred:X", "file": "data/x.json"}}]))
    lanes = [first, second, third, broken]
    merged = po.merge_sources_union([json.loads((lane / "sources.json").read_text()) for lane in lanes])

    sources, audit = po._merge_track_research_data([str(lane) for lane in lanes], str(handoff), merged)

    assert audit == {"series": 2, "unavailable_lanes": 1, "dropped_references": 2}
    assert [("dataset" in source) for source in sources] == [True, False, True, False]
    assert sources[1]["content"] == merged[1]["content"]  # the colliding page text stays citable
    (handoff / "sources.json").write_text(json.dumps(sources))
    carrier = load_official_data(handoff)
    assert {r["series"]: (r["source_id"], r["observations"][0]["value"]) for r in carrier["series"]} == {
        "fred:UNRATE": ("S1", 4.2), "fred:DGS10": ("S3", dgs10.observations[0].value)}
    artifacts = po._research_data_artifacts(str(handoff))  # the merged tree passes the seal reader
    assert (handoff / row["file"]).read_bytes() == (third / row["file"]).read_bytes() == artifacts[row["file"]]


def test_track_merge_without_lane_data_leaves_sources_untouched(tmp_path):
    handoff = tmp_path / "handoff"
    lane = handoff / "track_0"
    lane.mkdir(parents=True)
    sources = [{"url": "https://example.org/a", "content": "web page"}]
    assert po._merge_track_research_data([str(lane)], str(handoff), sources) == (
        sources, {"series": 0, "unavailable_lanes": 0, "dropped_references": 0})
    assert not (handoff / "data").exists()


def _merge_two_real_lanes(tmp_path, monkeypatch, metas=None):
    """Run the deterministic K=2 lane merge on real FRED captures (one per lane)."""
    from official_data_replay import publish, replay
    for name, value in {"RESEARCH_GLOBAL_SYNTHESIS": False, "RESEARCH_TRACK_RECONCILE": False,
                        "RESEARCH_COMPACT_MERGED_DOSSIER": False, "DEERFLOW_SUBAGENTS": False,
                        "DEERFLOW_DUAL_TRACK": False, "DEERFLOW_MODEL": "claude"}.items():
        monkeypatch.setattr(po.Config, name, value, raising=False)
    monkeypatch.setattr(po, "_sync_deerflow_bridge_if_stale", lambda _path: None)
    monkeypatch.setattr(po.PipelineManager, "save", classmethod(lambda cls, state: None))
    captures = {1: "fred_unrate_2024", 2: "fred_dgs10_daily"}

    def fake_run(prompt, handoff_dir, **kwargs):
        folder = Path(handoff_dir)
        lane = int(folder.name.split("_")[-1])
        series = replay(captures[lane], tmp_path)
        publish([series], folder)
        if metas:
            (folder / "meta.json").write_text(json.dumps(metas[lane]))
        row = json.loads((folder / "data/datasets.json").read_text())["series"][0]
        sources = [{"url": f"https://example.gov/lane-{lane}", "title": "Context", "tier": "S2"},
                   {"url": series.source_url, "title": series.title, "tier": "S1", "source_origin": "official_data",
                    "dataset": {"series": series.series, "file": row["file"]}}]
        (folder / "sources.json").write_text(json.dumps(sources))
        report = f"# Lane {lane}\n\n" + "Official baseline [S2] with context [S1]. " * 30
        return {"report": report, "report_path": str(folder / "research_report.md"), "actor_dossier": "",
                "actors": {"actors": [], "relationships": []}, "sources": sources, "timeline": None,
                "exit_code": 0, "research_telemetry": {"model": "claude", "depth": "deep", "wall_s": 1}}

    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", staticmethod(fake_run))
    handoff = tmp_path / "handoff"
    state = po.PipelineState(pipeline_id="pipe_lane_merge", prompt="Forecast rates", handoff_dir=str(handoff),
                             options={"depth": "deep", "research_language": "English", "research_model": "claude"})
    result = po.PipelineOrchestrator()._run_parallel_research_tracks(state, str(handoff), lambda *_: None, 2)
    return state, result, handoff


def test_parallel_lanes_without_global_synthesis_hand_off_their_official_data(tmp_path, monkeypatch):
    """L10 end to end: the deterministic K-lane merge leaves a handoff whose carrier holds
    every lane's real dataset, cited by the merged [S#] numbering."""
    state, result, handoff = _merge_two_real_lanes(tmp_path, monkeypatch)

    carrier = load_official_data(handoff)
    cited = {i + 1: s["dataset"]["series"] for i, s in enumerate(result["sources"]) if s.get("dataset")}
    assert {r["series"]: r["source_id"] for r in carrier["series"]} == {
        series: f"S{number}" for number, series in cited.items()}
    assert sorted(cited.values()) == ["fred:DGS10", "fred:UNRATE"]
    assert json.loads((handoff / "sources.json").read_text()) == result["sources"]
    assert state.options["official_data_merge"] == {"series": 2, "unavailable_lanes": 0, "dropped_references": 0}


def test_merged_lanes_keep_every_lane_capture_inside_the_run_window(tmp_path, monkeypatch):
    """D5 across lanes: the merged meta spans the earliest lane start to the latest lane
    finish, so a capture by a lane that outlived lane 1 past UTC midnight stays in the
    snapshot (DGS10 was retrieved at 22:07:48Z, after lane 1 finished)."""
    from app.services.official_data import historical_snapshot, research_run_window
    metas = {1: {"status": "completed", "started_at": "2026-10-10T23:10:00+00:00",
                 "finished_at": "2026-10-11T22:07:45+00:00"},
             2: {"status": "completed", "started_at": "2026-10-10T23:00:00+00:00",
                 "finished_at": "2026-10-11T22:30:00+00:00"}}
    _, _, handoff = _merge_two_real_lanes(tmp_path, monkeypatch, metas)

    window = research_run_window(handoff)
    assert window == {"started_at": "2026-10-10T23:00:00+00:00", "finished_at": "2026-10-11T22:30:00+00:00"}
    stats = {}
    text = historical_snapshot(load_official_data(handoff), as_of="2026-10-10", research_window=window, stats=stats)
    assert "Unemployment Rate" in text and "10-Year" in text
    assert stats == {"shown": 2, "excluded": {}}
