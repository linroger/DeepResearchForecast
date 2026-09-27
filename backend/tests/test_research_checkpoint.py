"""ITEM-3 研究断点续跑 + ITEM-14 --extract-only 只抽取打捞 的离线单测。

桥脚本（deerflow_bridge/deerflow_research.py）模块级只 import 标准库（``deerflow`` 相关
import 都在函数体内），故可从 backend 测试里直接 import 做纯函数/路由测试——零网络、零 LLM。
覆盖：
- 断点 write/parse/hash-mismatch（write_research_checkpoint / load_research_checkpoint /
  _question_hash 归一化）；
- pass-skip 规划纯函数（plan_research_resume / should_run_pass）；
- ResearchCheckpointer 落盘 + seed + enabled=False no-op；
- --extract-only argparse 路由（main：报告缺失/过小→非零退出零 LLM；报告够长→路由到
  run_extract_only，用 monkeypatch 拦截，不触发任何 LLM）；
- 编排器侧 _has_research_checkpoint（纯文件系统）。
"""

import json
import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_BACKEND)
_BRIDGE = os.path.join(_REPO_ROOT, "deerflow_bridge")
for _p in (_BACKEND, _BRIDGE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deerflow_research as dr  # noqa: E402
from app.services import pipeline_orchestrator as po  # noqa: E402


# ------------------------------------------------------------------ _question_hash

def test_question_hash_is_stable_and_normalized():
    h1 = dr._question_hash("Who wins the 2026 US House?")
    h2 = dr._question_hash("Who wins the 2026 US House?")
    assert h1 == h2 and len(h1) == 16
    # 归一化：折叠空白 + 去首尾 + 小写 → 表层差异不改 hash
    assert dr._question_hash("  who WINS   the 2026 us   house?  ") == h1
    # 不同问题 → 不同 hash
    assert dr._question_hash("Who wins the 2028 US House?") != h1


# ------------------------------------------------------ write / load round-trip

def test_checkpoint_write_and_load_roundtrip(tmp_path):
    dr.write_research_checkpoint(
        tmp_path,
        thread_id="research-abc123",
        completed_passes=["deep-opening", "deep-phase-1"],
        fetched_source_count=17,
        gaps=["gap A", "gap B"],
        depth="deep",
        question_hash=dr._question_hash("Q"),
    )
    p = tmp_path / dr.RESEARCH_CHECKPOINT_FILENAME
    assert p.exists()
    obj = dr.load_research_checkpoint(tmp_path)
    assert obj is not None
    assert obj["thread_id"] == "research-abc123"
    assert obj["completed_passes"] == ["deep-opening", "deep-phase-1"]
    assert obj["fetched_source_count"] == 17
    assert obj["depth"] == "deep"
    assert obj["question_hash"] == dr._question_hash("Q")
    assert obj["version"] == dr._RESEARCH_CHECKPOINT_VERSION
    assert "updated_at" in obj


def test_checkpoint_gaps_are_capped(tmp_path):
    many = [f"gap-{i}" for i in range(500)]
    dr.write_research_checkpoint(
        tmp_path, thread_id="t", completed_passes=[], fetched_source_count=0,
        gaps=many, depth="deep", question_hash="h",
    )
    obj = dr.load_research_checkpoint(tmp_path)
    assert len(obj["gaps"]) == dr._RESEARCH_CHECKPOINT_MAX_GAPS


def test_load_missing_or_corrupt_returns_none(tmp_path):
    # 缺失
    assert dr.load_research_checkpoint(tmp_path) is None
    # None out_dir
    assert dr.load_research_checkpoint(None) is None
    # 损坏 JSON → None（degrade-safe，不抛）
    (tmp_path / dr.RESEARCH_CHECKPOINT_FILENAME).write_text("{not json", encoding="utf-8")
    assert dr.load_research_checkpoint(tmp_path) is None
    # 合法 JSON 但非 dict → None
    (tmp_path / dr.RESEARCH_CHECKPOINT_FILENAME).write_text("[1,2,3]", encoding="utf-8")
    assert dr.load_research_checkpoint(tmp_path) is None


def test_write_checkpoint_none_out_dir_is_noop():
    # 不抛，不写
    dr.write_research_checkpoint(
        None, thread_id="t", completed_passes=[], fetched_source_count=0,
        gaps=[], depth="deep", question_hash="h",
    )


# ------------------------------------------------------ plan_research_resume (pure)

def test_plan_resume_happy_path():
    q = "Will X happen by 2027?"
    ckpt = {
        "thread_id": "research-xyz",
        "question_hash": dr._question_hash(q),
        "depth": "deep",
        "completed_passes": ["deep-opening", "deep-phase-2"],
    }
    plan = dr.plan_research_resume(ckpt, q, "deep")
    assert plan["resume"] is True
    assert plan["thread_id"] == "research-xyz"
    assert plan["completed_passes"] == ["deep-opening", "deep-phase-2"]
    assert plan["reason"] == "ok"


def test_plan_resume_hash_mismatch():
    ckpt = {
        "thread_id": "research-xyz",
        "question_hash": dr._question_hash("original question"),
        "depth": "deep",
        "completed_passes": ["deep-opening"],
    }
    plan = dr.plan_research_resume(ckpt, "a totally different question", "deep")
    assert plan["resume"] is False
    assert plan["thread_id"] is None
    assert "hash mismatch" in plan["reason"]


def test_plan_resume_depth_mismatch():
    q = "Q"
    ckpt = {"thread_id": "t", "question_hash": dr._question_hash(q),
            "depth": "standard", "completed_passes": []}
    plan = dr.plan_research_resume(ckpt, q, "deep")
    assert plan["resume"] is False
    assert "depth mismatch" in plan["reason"]


def test_plan_resume_missing_and_no_thread_id():
    assert dr.plan_research_resume(None, "Q", "deep")["resume"] is False
    assert dr.plan_research_resume({}, "Q", "deep")["reason"] == "checkpoint missing thread_id"
    # thread_id 空串也视为缺失
    assert dr.plan_research_resume(
        {"thread_id": "", "question_hash": dr._question_hash("Q"), "depth": "deep"},
        "Q", "deep")["resume"] is False


def test_plan_resume_non_list_completed_passes_coerced():
    q = "Q"
    ckpt = {"thread_id": "t", "question_hash": dr._question_hash(q),
            "depth": "deep", "completed_passes": "not-a-list"}
    plan = dr.plan_research_resume(ckpt, q, "deep")
    assert plan["resume"] is True
    assert plan["completed_passes"] == []


@pytest.mark.parametrize(
    ("field", "expected", "reason"),
    [
        ("expected_run_id", "run-other", "run_id mismatch"),
        ("expected_attempt_id", "attempt-other", "attempt_id mismatch"),
        ("expected_lane_id", "lane-other", "lane_id mismatch"),
    ],
)
def test_plan_resume_rejects_cross_lineage_checkpoint(
        tmp_path, field, expected, reason):
    dr.write_research_checkpoint(
        tmp_path,
        thread_id="thread-a",
        completed_passes=["deep-opening"],
        fetched_source_count=2,
        gaps=[],
        depth="deep",
        question_hash=dr._question_hash("Q"),
        run_id="run-a",
        attempt_id="attempt-a",
        lane_id="lane-a",
    )
    checkpoint = dr.load_research_checkpoint(tmp_path)
    plan = dr.plan_research_resume(
        checkpoint, "Q", "deep", **{field: expected})
    assert plan["resume"] is False
    assert reason in plan["reason"]


def test_plan_resume_rejects_tampered_checkpoint_identity(tmp_path):
    dr.write_research_checkpoint(
        tmp_path,
        thread_id="thread-a",
        completed_passes=["deep-opening"],
        fetched_source_count=2,
        gaps=[],
        depth="deep",
        question_hash=dr._question_hash("Q"),
    )
    checkpoint = dr.load_research_checkpoint(tmp_path)
    checkpoint["completed_passes"].append("deep-phase-1")
    plan = dr.plan_research_resume(checkpoint, "Q", "deep")
    assert plan["resume"] is False
    assert plan["reason"] == "checkpoint identity mismatch"


# ------------------------------------------------------ should_run_pass (pure planner)

def test_should_run_pass_no_resume_always_runs():
    assert dr.should_run_pass("deep-phase-2", set(), False) is True
    assert dr.should_run_pass("deep-phase-2", {"deep-phase-2"}, False) is True


def test_should_run_pass_resume_skips_completed():
    completed = {"deep-opening", "deep-phase-1"}
    assert dr.should_run_pass("deep-opening", completed, True) is False
    assert dr.should_run_pass("deep-phase-1", completed, True) is False
    assert dr.should_run_pass("deep-phase-2", completed, True) is True
    # 空完成集 → 全部照跑
    assert dr.should_run_pass("deep-opening", set(), True) is True


# ------------------------------------------------------ ResearchCheckpointer

def test_checkpointer_record_pass_persists(tmp_path):
    ck = dr.ResearchCheckpointer(tmp_path, "research-tid", "deep", "Q", enabled=True)
    ck.record_pass("deep-opening", gaps=["g1"], fetched_source_count=5)
    ck.record_pass("deep-phase-1", fetched_source_count=9)
    obj = dr.load_research_checkpoint(tmp_path)
    assert obj["thread_id"] == "research-tid"
    assert obj["completed_passes"] == ["deep-opening", "deep-phase-1"]
    assert obj["fetched_source_count"] == 9
    assert obj["question_hash"] == dr._question_hash("Q")
    # 重复记录不产生重复项
    ck.record_pass("deep-opening")
    obj2 = dr.load_research_checkpoint(tmp_path)
    assert obj2["completed_passes"].count("deep-opening") == 1


def test_checkpointer_seed_completed(tmp_path):
    ck = dr.ResearchCheckpointer(tmp_path, "t", "deep", "Q", enabled=True)
    ck.seed_completed(["deep-opening", "deep-phase-1"])
    ck.record_pass("deep-phase-2", fetched_source_count=3)
    obj = dr.load_research_checkpoint(tmp_path)
    assert obj["completed_passes"] == ["deep-opening", "deep-phase-1", "deep-phase-2"]


def test_checkpointer_disabled_is_noop(tmp_path):
    ck = dr.ResearchCheckpointer(tmp_path, "t", "deep", "Q", enabled=False)
    ck.record_pass("deep-opening", fetched_source_count=5)
    ck.update_progress(gaps=["g"])
    assert not (tmp_path / dr.RESEARCH_CHECKPOINT_FILENAME).exists()


def test_checkpointer_none_out_dir_is_noop():
    ck = dr.ResearchCheckpointer(None, "t", "deep", "Q", enabled=True)
    assert ck.enabled is False
    ck.record_pass("deep-opening")  # 不抛


# ------------------------------------------------------ --extract-only argparse routing (no LLM)

def _run_main(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["deerflow_research.py", *argv])
    return dr.main()


def test_extract_only_missing_report_exits_nonzero(tmp_path, monkeypatch):
    # 无 research_report.md → 前置门在任何 LLM/凭据校验之前诚实非零退出。
    rc = _run_main(["--extract-only", "--out-dir", str(tmp_path), "--prompt", "Q"], monkeypatch)
    assert rc == 3
    # 未跑抽取 → 无 actors.json
    assert not (tmp_path / "actors.json").exists()
    # meta 记为 failed
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "failed"


def test_extract_only_too_small_report_exits_nonzero(tmp_path, monkeypatch):
    (tmp_path / dr.REPORT_FILENAME).write_text("tiny", encoding="utf-8")
    rc = _run_main(["--extract-only", "--out-dir", str(tmp_path), "--prompt", "Q"], monkeypatch)
    assert rc == 3
    assert not (tmp_path / "actors.json").exists()


def test_extract_only_valid_report_routes_to_run_extract_only(tmp_path, monkeypatch):
    # 报告够长 → 路由到 run_extract_only（monkeypatch 拦截，零 LLM）。用 minimax 让凭据校验
    # 只查 MINIMAX_API_KEY（避免触碰 claude OAuth 加载）。
    (tmp_path / dr.REPORT_FILENAME).write_text("x" * 1000, encoding="utf-8")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    called = {}

    def _fake_extract_only(question, out_dir, args, meta, plog, write_meta):
        called["hit"] = True
        called["question"] = question
        called["extract_only"] = args.extract_only
        plog.close()
        return 0

    monkeypatch.setattr(dr, "run_extract_only", _fake_extract_only)
    rc = _run_main(
        ["--extract-only", "--model", "minimax", "--out-dir", str(tmp_path), "--prompt", "Q1"],
        monkeypatch,
    )
    assert rc == 0
    assert called.get("hit") is True
    assert called.get("question") == "Q1"
    assert called.get("extract_only") is True


def test_normal_run_does_not_route_to_extract_only(tmp_path, monkeypatch):
    # 无 --extract-only → 不走 run_extract_only（拦截，若被调用则测试失败）。用一个必然在客户端
    # 构造/凭据阶段短路的 model，确认路由分支不误触发抽取-only。
    monkeypatch.setattr(dr, "run_extract_only",
                        lambda *a, **k: pytest.fail("run_extract_only 不应在正常运行被调用"))
    monkeypatch.setenv("MINIMAX_API_KEY", "")  # 缺 key → 凭据前置门非零退出（在 try 之前）
    rc = _run_main(
        ["--model", "minimax", "--out-dir", str(tmp_path), "--prompt", "Q"],
        monkeypatch,
    )
    assert rc == 3  # missing MINIMAX_API_KEY，且从未触碰 run_extract_only


# ------------------------------------------------------ 编排器 _has_research_checkpoint

def test_orchestrator_has_research_checkpoint(tmp_path):
    hd = str(tmp_path)
    assert po._has_research_checkpoint(hd) is False
    cp = tmp_path / "research_checkpoint.json"
    cp.write_text("", encoding="utf-8")  # 空文件 → 视为无
    assert po._has_research_checkpoint(hd) is False
    cp.write_text(json.dumps({"thread_id": "t"}), encoding="utf-8")
    assert po._has_research_checkpoint(hd) is True


# ------------------------------------------ parent explicit-resume authority

def _write_parent_resume_checkpoint(tmp_path):
    dr.write_research_checkpoint(
        tmp_path,
        thread_id="research-durable-thread",
        completed_passes=["deep-opening", "deep-phase-1"],
        fetched_source_count=12,
        gaps=["remaining gap"],
        depth="deep",
        question_hash=dr._question_hash("Will X happen?"),
        run_id="pipe-resume",
        attempt_id="task-original",
        lane_id="outer-track-1",
    )
    return dr.load_research_checkpoint(tmp_path)


def test_parent_accepts_exact_prior_attempt_for_fresh_task_resume(tmp_path):
    checkpoint = _write_parent_resume_checkpoint(tmp_path)

    lineage = po._validated_research_checkpoint_lineage(
        str(tmp_path),
        prompt="Will X happen?",
        depth="deep",
        run_id="pipe-resume",
        lane_id="outer-track-1",
        expected_attempt_ids={"task-original", "task-fresh"},
    )

    assert lineage == {
        "attempt_id": "task-original",
        "checkpoint_id": checkpoint["checkpoint_id"],
        "thread_id": "research-durable-thread",
    }
    bridge_plan = dr.plan_research_resume(
        checkpoint,
        "Will X happen?",
        "deep",
        expected_run_id="pipe-resume",
        expected_attempt_id=lineage["attempt_id"],
        expected_lane_id="outer-track-1",
        expected_checkpoint_id=lineage["checkpoint_id"],
    )
    assert bridge_plan["resume"] is True
    assert dr.should_run_pass(
        "deep-opening", bridge_plan["completed_passes"], True
    ) is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"prompt": "Will Y happen?"},
        {"run_id": "pipe-other"},
        {"lane_id": "outer-track-2"},
        {"expected_attempt_ids": {"task-other"}},
    ],
)
def test_parent_rejects_cross_lineage_resume_checkpoint(tmp_path, overrides):
    _write_parent_resume_checkpoint(tmp_path)
    arguments = {
        "prompt": "Will X happen?",
        "depth": "deep",
        "run_id": "pipe-resume",
        "lane_id": "outer-track-1",
        "expected_attempt_ids": {"task-original"},
        **overrides,
    }

    assert po._validated_research_checkpoint_lineage(
        str(tmp_path), **arguments
    ) == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("thread_id", "research-tampered-thread"),
        ("completed_passes", ["deep-opening", "deep-phase-2"]),
        ("fetched_source_count", 999),
        ("gaps", ["rewritten gap"]),
    ],
)
def test_parent_rejects_tampered_resume_checkpoint_identity(
    tmp_path, field, value,
):
    checkpoint = _write_parent_resume_checkpoint(tmp_path)
    checkpoint[field] = value
    (tmp_path / dr.RESEARCH_CHECKPOINT_FILENAME).write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    assert po._validated_research_checkpoint_lineage(
        str(tmp_path),
        prompt="Will X happen?",
        depth="deep",
        run_id="pipe-resume",
        lane_id="outer-track-1",
        expected_attempt_ids={"task-original"},
    ) == {}


def test_parent_rejects_resealed_malformed_completed_passes(tmp_path):
    checkpoint = _write_parent_resume_checkpoint(tmp_path)
    checkpoint["completed_passes"] = ["deep-opening", {"forged": True}]
    checkpoint["checkpoint_id"] = dr._checkpoint_identity(checkpoint)
    (tmp_path / dr.RESEARCH_CHECKPOINT_FILENAME).write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    assert po._validated_research_checkpoint_lineage(
        str(tmp_path),
        prompt="Will X happen?",
        depth="deep",
        run_id="pipe-resume",
        lane_id="outer-track-1",
        expected_attempt_ids={"task-original"},
    ) == {}


def test_runner_uses_prior_checkpoint_identity_with_fresh_budget_database(
    tmp_path, monkeypatch,
):
    deerflow_dir = tmp_path / "deer-flow"
    deerflow_dir.mkdir()
    (deerflow_dir / "deerflow_research.py").write_text(
        "# test entrypoint\n", encoding="utf-8"
    )
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (handoff / "research_report.md").write_text(
        "research evidence " * 40, encoding="utf-8"
    )
    captured = {}

    class CompletedProcess:
        pid = 4322
        stdout = []

        @staticmethod
        def poll():
            return 0

        @staticmethod
        def wait(timeout=None):
            return 0

    def fake_popen(*args, **kwargs):
        captured["cmd"] = args[0]
        captured["env"] = kwargs["env"]
        return CompletedProcess()

    monkeypatch.setattr(po.Config, "DEERFLOW_DIR", str(deerflow_dir))
    monkeypatch.setattr(po.Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(po, "_sync_deerflow_bridge_if_stale", lambda _path: None)
    monkeypatch.setattr(po.subprocess, "Popen", fake_popen)
    fresh_db = tmp_path / "fresh-task" / "research_budget.sqlite3"
    fresh_telemetry = tmp_path / "research_budget.json"

    po.DeerFlowResearchRunner.run(
        "Will X happen?",
        str(handoff),
        on_progress=lambda _pct, _message: None,
        timeout=10,
        resume=True,
        budget_db_path=str(fresh_db),
        budget_telemetry_path=str(fresh_telemetry),
        budget_run_id="pipe-resume",
        budget_lane_id="outer-track-1",
        budget_epoch="task-fresh",
        resume_attempt_id="task-original",
        resume_checkpoint_id="checkpoint_parent_validated",
    )

    assert "--resume" in captured["cmd"]
    assert captured["env"]["RESEARCH_BUDGET_DB"] == str(fresh_db)
    assert captured["env"]["RESEARCH_BUDGET_EPOCH"] == "task-original"
    assert captured["env"]["RESEARCH_BUDGET_RUN_ID"] == "pipe-resume"
    assert captured["env"]["RESEARCH_BUDGET_LANE_ID"] == "outer-track-1"
    assert (
        captured["env"]["RESEARCH_CHECKPOINT_ID"]
        == "checkpoint_parent_validated"
    )


def test_extract_only_salvage_of_a_v3_handoff_keeps_its_meta(tmp_path, monkeypatch):
    """The parent salvages a watchdog-killed v3 run with the legacy extract-only
    path; the v3 provenance and research_quality block must survive it."""
    (tmp_path / dr.REPORT_FILENAME).write_text("x" * 1000, encoding="utf-8")
    prior = {"status": "running", "research_engine": "v3", "error": "stale",
             "research_quality": {"score": 0.61, "degraded": True,
                                  "degradation": ["1 section(s) cut by the output cap and trimmed: X"]},
             "v3_preset": {"depth": "standard"}}
    (tmp_path / "meta.json").write_text(json.dumps(prior), encoding="utf-8")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    seen = {}

    def _fake_extract_only(question, out_dir, args, meta, plog, write_meta):
        seen["meta"] = dict(meta)
        plog.close()
        return 0

    monkeypatch.setattr(dr, "run_extract_only", _fake_extract_only)
    rc = _run_main(["--extract-only", "--model", "minimax", "--out-dir", str(tmp_path), "--prompt", "Q1"],
                   monkeypatch)
    assert rc == 0
    meta = seen["meta"]
    assert meta["research_engine"] == "v3" and meta["salvage"]["mode"] == "extract_only"
    assert meta["research_quality"] == prior["research_quality"] and meta["v3_preset"] == {"depth": "standard"}
    assert meta["status"] == "running" and "error" not in meta  # lifecycle keys are the salvage run's own


def test_extract_only_of_a_legacy_handoff_starts_a_fresh_meta(tmp_path, monkeypatch):
    (tmp_path / dr.REPORT_FILENAME).write_text("x" * 1000, encoding="utf-8")
    (tmp_path / "meta.json").write_text(json.dumps({"research_engine": "legacy", "custom": 1}), encoding="utf-8")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    seen = {}

    def _fake_extract_only(question, out_dir, args, meta, plog, write_meta):
        seen["meta"] = dict(meta)
        plog.close()
        return 0

    monkeypatch.setattr(dr, "run_extract_only", _fake_extract_only)
    assert _run_main(["--extract-only", "--model", "minimax", "--out-dir", str(tmp_path), "--prompt", "Q"],
                     monkeypatch) == 0
    assert "custom" not in seen["meta"] and "salvage" not in seen["meta"]
