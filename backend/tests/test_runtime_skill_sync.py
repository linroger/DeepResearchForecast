"""Regression tests for authoritative runtime skill bundle deployment."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "deerflow_bridge" / "runtime_skill_sync.py"


@pytest.fixture(scope="module")
def skill_sync_module():
    spec = importlib.util.spec_from_file_location(
        "drf_runtime_skill_sync_tests",
        HELPER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def research_bridge_module():
    path = REPO_ROOT / "deerflow_bridge" / "deerflow_research.py"
    spec = importlib.util.spec_from_file_location(
        "drf_runtime_skill_sync_bridge_tests",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_skill(root: Path, name: str, files: dict[str, str]) -> Path:
    skill = root / name
    for relative, content in files.items():
        path = skill / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return skill


def _public_root(tmp_path: Path) -> Path:
    skills = tmp_path / "runtime" / "skills"
    skills.mkdir(parents=True)
    return skills / "public"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_sync_builds_deterministic_manifest_and_prunes_destination_only_files(
    tmp_path,
    skill_sync_module,
):
    source = tmp_path / "source"
    public = _public_root(tmp_path)
    _write_skill(source, "alpha", {
        "SKILL.md": "---\nname: alpha\n---\n",
        "references/guide.md": "lazy guide\n",
        "scripts/render.py": "print('render')\n",
    })
    _write_skill(public, "alpha", {
        "SKILL.md": "stale\n",
        "references/deleted.md": "destination only\n",
        ".DS_Store": "generated noise\n",
    })
    _write_skill(public, "vendor-skill", {"SKILL.md": "vendor\n"})

    first = skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("alpha",),
    )

    assert first["outcome"] == "updated"
    assert first["source_manifest_hash"] == first["deployed_manifest_hash"]
    assert first["runtime_generated_allowlist"] == []
    assert first["skills"]["alpha"]["lazy_resource_hashes"] == {
        "references/guide.md": first["skills"]["alpha"]["files"][1]["sha256"],
        "scripts/render.py": first["skills"]["alpha"]["files"][2]["sha256"],
    }
    assert not (public / "alpha" / "references" / "deleted.md").exists()
    assert not (public / "alpha" / ".DS_Store").exists()
    assert (public / "vendor-skill" / "SKILL.md").read_text() == "vendor\n"
    assert (public / skill_sync_module.STATE_FILENAME).is_file()

    before = _tree_bytes(public)
    second = skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("alpha",),
    )
    assert second["outcome"] == "verified"
    assert _tree_bytes(public) == before


def test_source_rename_and_deletion_prune_previously_managed_skill(
    tmp_path,
    skill_sync_module,
):
    source = tmp_path / "source"
    public = _public_root(tmp_path)
    _write_skill(source, "old-name", {"SKILL.md": "old\n"})
    _write_skill(public, "vendor-skill", {"SKILL.md": "vendor\n"})
    skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("old-name",),
    )

    (source / "old-name").rename(source / "new-name")
    renamed = skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("new-name",),
    )
    assert renamed["pruned_skills"] == ["old-name"]
    assert not (public / "old-name").exists()
    assert (public / "new-name" / "SKILL.md").read_text() == "old\n"

    shutil.rmtree(source / "new-name")
    deleted = skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=(),
    )
    assert deleted["pruned_skills"] == ["new-name"]
    assert not (public / "new-name").exists()
    assert (public / "vendor-skill" / "SKILL.md").read_text() == "vendor\n"


def test_injected_stage_copy_failure_leaves_live_bundle_unchanged(
    tmp_path,
    monkeypatch,
    skill_sync_module,
):
    source = tmp_path / "source"
    public = _public_root(tmp_path)
    _write_skill(source, "alpha", {
        "SKILL.md": "version one\n",
        "references/guide.md": "one\n",
    })
    skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("alpha",),
    )
    before = _tree_bytes(public)
    (source / "alpha" / "SKILL.md").write_text("version two\n", encoding="utf-8")
    (source / "alpha" / "references" / "guide.md").write_text(
        "two\n", encoding="utf-8"
    )

    real_copy2 = skill_sync_module.shutil.copy2

    def fail_source_copy(source_path, destination_path, *args, **kwargs):
        if Path(source_path).is_relative_to(source):
            raise OSError("injected copy failure")
        return real_copy2(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(skill_sync_module.shutil, "copy2", fail_source_copy)
    with pytest.raises(
        skill_sync_module.SkillSyncError,
        match="injected copy failure",
    ):
        skill_sync_module.sync_runtime_skills(
            source,
            public,
            required_skills=("alpha",),
        )

    assert _tree_bytes(public) == before
    assert not list(public.parent.glob(f"{skill_sync_module.STAGE_PREFIX}*"))


def test_concurrent_cli_syncs_serialize_and_end_on_one_verified_bundle(tmp_path):
    source = tmp_path / "source"
    public = _public_root(tmp_path)
    skill = _write_skill(source, "alpha", {"SKILL.md": "alpha\n"})
    (skill / "assets").mkdir()
    (skill / "assets" / "large.bin").write_bytes(b"x" * (4 * 1024 * 1024))
    command = [
        sys.executable,
        str(HELPER_PATH),
        "--source-root", str(source),
        "--deployed-public-root", str(public),
        "--required-skill", "alpha",
    ]

    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    completed = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], completed
    payloads = [json.loads(stdout) for stdout, _stderr in completed]
    assert sorted(payload["outcome"] for payload in payloads) == ["updated", "verified"]
    assert len({payload["deployed_manifest_hash"] for payload in payloads}) == 1


def test_required_source_bundle_missing_fails_closed(tmp_path, skill_sync_module):
    source = tmp_path / "source"
    source.mkdir()
    public = _public_root(tmp_path)

    with pytest.raises(
        skill_sync_module.SkillSyncError,
        match="required runtime skill source bundle.*deep-research",
    ):
        skill_sync_module.sync_runtime_skills(
            source,
            public,
            required_skills=("deep-research",),
        )


def test_runtime_verification_rejects_post_sync_tampering(
    tmp_path,
    skill_sync_module,
):
    source = tmp_path / "source"
    public = _public_root(tmp_path)
    _write_skill(source, "alpha", {
        "SKILL.md": "alpha\n",
        "references/guide.md": "guide\n",
    })
    payload = skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("alpha",),
    )
    verified = skill_sync_module.verify_runtime_sync_payload(payload, public)
    assert verified["runtime_verified"] is True

    (public / "alpha" / "references" / "guide.md").write_text(
        "tampered\n", encoding="utf-8"
    )
    with pytest.raises(
        skill_sync_module.SkillSyncError,
        match="changed before execution",
    ):
        skill_sync_module.verify_runtime_sync_payload(payload, public)


def test_bridge_rehashes_parent_payload_for_durable_run_telemetry(
    tmp_path,
    monkeypatch,
    skill_sync_module,
    research_bridge_module,
):
    source = tmp_path / "source"
    public = _public_root(tmp_path)
    _write_skill(source, "alpha", {
        "SKILL.md": "alpha\n",
        "references/guide.md": "guide\n",
    })
    payload = skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("alpha",),
    )
    monkeypatch.setitem(sys.modules, "runtime_skill_sync", skill_sync_module)
    monkeypatch.setattr(
        research_bridge_module,
        "__file__",
        str(public.parents[1] / "deerflow_research.py"),
    )
    monkeypatch.setenv("DRF_RUNTIME_SKILL_SYNC_REQUIRED", "1")
    monkeypatch.setenv(
        "DRF_RUNTIME_SKILL_SYNC",
        json.dumps(payload, sort_keys=True),
    )

    telemetry = research_bridge_module.runtime_skill_sync_telemetry()

    assert telemetry["runtime_verified"] is True
    assert telemetry["source_manifest_hash"] == telemetry["deployed_manifest_hash"]
    assert telemetry["deployed_path"] == str(public.resolve())
    assert telemetry["skills"]["alpha"]["lazy_resource_hashes"] == {
        "references/guide.md": skill_sync_module._sha256_file(
            source / "alpha" / "references" / "guide.md"
        )
    }


def test_session_hook_litter_is_never_deployed(tmp_path, skill_sync_module):
    """Agent-session hooks write ``logs/`` and ``.claude/`` trees into whatever
    directory a shell ran in (observed under forecast-visuals/scripts/).  They
    hold session transcripts, so neither they nor bytecode / Finder noise may
    reach the runtime bundle, its manifest, or its identity hash."""
    source = tmp_path / "source"
    public = _public_root(tmp_path)
    _write_skill(source, "alpha", {
        "SKILL.md": "---\nname: alpha\n---\n",
        "scripts/render.py": "print('render')\n",
        "scripts/logs/user_prompt_submit.json": "{}\n",
        "scripts/logs/session-1/pre_tool_use.json": "{}\n",
        "scripts/.claude/data/sessions/session-1.json": "{}\n",
        "logs/top_level.json": "{}\n",
        "scripts/__pycache__/render.cpython-312.pyc": "bytecode\n",
        "scripts/.DS_Store": "finder\n",
    })

    payload = skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("alpha",),
    )

    manifest = payload["skills"]["alpha"]
    assert [entry["path"] for entry in manifest["files"]] == [
        "SKILL.md", "scripts/render.py"]
    assert manifest["directories"] == ["scripts"]
    assert sorted(_tree_bytes(public / "alpha")) == ["SKILL.md", "scripts/render.py"]
    assert not (public / "alpha" / "scripts" / "logs").exists()
    assert not (public / "alpha" / "scripts" / ".claude").exists()
    assert not (public / "alpha" / "logs").exists()

    # New litter written after a sync leaves the bundle identity untouched.
    (source / "alpha" / "scripts" / "logs" / "later.json").write_text(
        "{}\n", encoding="utf-8")
    again = skill_sync_module.sync_runtime_skills(
        source,
        public,
        required_skills=("alpha",),
    )
    assert again["outcome"] == "verified"
    assert again["source_manifest_hash"] == payload["source_manifest_hash"]


def test_noise_filter_matches_whole_path_components_only(skill_sync_module):
    is_noise = skill_sync_module._is_source_noise
    for noisy in (
        "logs", "scripts/logs/a.json", ".claude/x.json",
        "a/.claude/data/s.json", "scripts/__pycache__/m.pyc",
        ".DS_Store", "references/.DS_Store", "scripts/m.pyo",
    ):
        assert is_noise(Path(noisy)), noisy
    for kept in (
        "SKILL.md", "scripts/render_data.py", "references/logs-and-metrics.md",
        "scripts/catalog.py", "assets/claude.svg", "references/changelogs/a.md",
    ):
        assert not is_noise(Path(kept)), kept


def test_default_required_skills_exist_in_the_source_tree(skill_sync_module):
    """The production launch guard deploys DEFAULT_REQUIRED_SKILLS and fails
    closed when any bundle is missing, so every name must ship a SKILL.md."""
    assert skill_sync_module.DEFAULT_REQUIRED_SKILLS == (
        "actor-ontology-research",
        "data-sources",
        "data-visuals",
        "deep-research",
        "forecast-visuals",
        "prediction-markets",
    )
    source_root = REPO_ROOT / "deerflow_bridge" / "skills"
    missing = [
        name for name in skill_sync_module.DEFAULT_REQUIRED_SKILLS
        if not (source_root / name / "SKILL.md").is_file()
    ]
    assert not missing, f"required runtime skills without a SKILL.md: {missing}"
