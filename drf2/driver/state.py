"""Stage state machine + schema-versioned, atomically-persisted pipeline state.

Ports the ESSENTIAL semantics of pipeline_orchestrator's PipelineState/PipelineManager
(schema_version + migrations + atomic save + resume) without its 4.2K LOC. Resume
policy: a stage marked ``completed`` is skipped only when its artifact-manifest hashes
verify (see manifest.py); otherwise it is re-run — never trust a bare status flag
(the corpus review found 8/13 legacy runs "completed" with broken deliverables).
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .legacy import ensure_backend_importable

ensure_backend_importable()
from app.utils.atomic import write_json_atomic  # noqa: E402 — 复用后端原子写（REDESIGN §3）

SCHEMA_VERSION = 1
STAGES: tuple[str, ...] = ("research", "ontology", "graph", "prepare", "run", "report")

# 合法状态迁移。completed→running 允许：manifest 校验失败时强制重建（I-4-3 语义）。
_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running"},
    "running": {"completed", "failed"},
    "failed": {"running"},
    "completed": {"running"},
}
_PIPELINE_STATUSES = ("pending", "running", "completed", "failed", "cancelled")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncompatibleStateSchema(RuntimeError):
    """State file written by a NEWER driver — refuse to resume rather than corrupt it."""

    def __init__(self, pipeline_id: str, file_version: int):
        super().__init__(
            f"pipeline {pipeline_id}: state schema_version={file_version} > "
            f"driver SCHEMA_VERSION={SCHEMA_VERSION}; upgrade the driver to resume"
        )
        self.file_version = file_version


class InvalidTransition(RuntimeError):
    pass


@dataclass
class StageRecord:
    name: str
    status: str = "pending"  # pending | running | completed | failed
    message: str = ""
    error: Optional[str] = None
    health: str = "unknown"  # unknown | ok | degraded | failed (gate verdict)
    issues: list[str] = field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    attempts: int = 0
    reused: bool = False  # resume 时经 manifest 校验后跳过
    artifacts: dict[str, str] = field(default_factory=dict)  # 名称 → 绝对路径

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageRecord":
        known = {f for f in cls.__dataclass_fields__}  # 前向兼容：忽略未知键
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class DriverState:
    pipeline_id: str
    question: str
    schema_version: int = SCHEMA_VERSION
    status: str = "pending"
    current_stage: str = ""
    thread_id: str = ""
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)
    error: Optional[str] = None
    seeds: list[int] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    stages: dict[str, StageRecord] = field(default_factory=dict)

    @classmethod
    def new(cls, question: str, pipeline_id: Optional[str] = None) -> "DriverState":
        pid = pipeline_id or uuid.uuid4().hex[:12]
        state = cls(pipeline_id=pid, question=question, thread_id=f"drf2-{pid}")
        state.stages = {name: StageRecord(name=name) for name in STAGES}
        return state

    # ---------------------------------------------------------------- transitions
    def _stage(self, name: str) -> StageRecord:
        if name not in STAGES:
            raise KeyError(f"unknown stage: {name}")
        return self.stages.setdefault(name, StageRecord(name=name))

    def _transition(self, name: str, to: str) -> StageRecord:
        st = self._stage(name)
        allowed = _STAGE_TRANSITIONS.get(st.status, set())
        if to not in allowed:
            raise InvalidTransition(f"stage {name}: {st.status} → {to} not allowed")
        st.status = to
        self.updated_at = utcnow()
        return st

    def start_stage(self, name: str) -> StageRecord:
        st = self._transition(name, "running")
        st.started_at = utcnow()
        st.finished_at = None
        st.error = None
        st.reused = False
        st.attempts += 1
        self.current_stage = name
        self.status = "running"
        return st

    def complete_stage(self, name: str, *, health: str = "ok",
                       issues: Optional[list[str]] = None,
                       artifacts: Optional[dict[str, str]] = None,
                       message: str = "完成") -> StageRecord:
        st = self._transition(name, "completed")
        st.finished_at = utcnow()
        st.health = health
        st.issues = list(issues or [])
        st.message = message
        if artifacts:
            st.artifacts.update(artifacts)
        return st

    def fail_stage(self, name: str, error: str) -> StageRecord:
        st = self._transition(name, "failed")
        st.finished_at = utcnow()
        st.error = error
        st.health = "failed"
        self.status = "failed"
        self.error = f"[{name}] {error}"
        return st

    def mark_stage_reused(self, name: str) -> StageRecord:
        """Resume：manifest 哈希核验通过 → 原地保留 completed，仅打 reused 痕。"""
        st = self._stage(name)
        if st.status != "completed":
            raise InvalidTransition(f"stage {name}: cannot reuse a {st.status} stage")
        st.reused = True
        st.message = "resume：manifest 校验通过，复用产物"
        self.updated_at = utcnow()
        return st

    def mark_completed(self) -> None:
        self.status = "completed"
        self.current_stage = ""
        self.updated_at = utcnow()

    # ---------------------------------------------------------------- serialization
    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["stages"] = {k: v.to_dict() for k, v in self.stages.items()}
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DriverState":
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in (data or {}).items() if k in known and k != "stages"}
        state = cls(**kwargs)
        state.stages = {
            name: StageRecord.from_dict(sd if isinstance(sd, dict) else {"name": name})
            for name, sd in (data.get("stages") or {}).items()
        }
        return state


# 迁移链：file_version → 把该版本的 dict 升到 version+1 的纯函数。v1 起步，当前为空。
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

# \A…\Z + fullmatch：``$`` 会放过尾随换行；纯点号 id（'.', '..'）另行拒绝，否则
# pipeline_dir('..') 会逃出 base_dir（INFRA-10）。
_ID_RE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")


class StateStore:
    """schema 版本化的 state.json 存取（原子写、迁移、损坏即报错——绝不静默吞状态）。"""

    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)

    def _validate_id(self, pipeline_id: str) -> str:
        if (not isinstance(pipeline_id, str) or not _ID_RE.fullmatch(pipeline_id)
                or not pipeline_id.strip(".")):
            raise ValueError(f"invalid pipeline_id: {pipeline_id!r}")
        return pipeline_id

    def pipeline_dir(self, pipeline_id: str) -> str:
        return os.path.join(self.base_dir, self._validate_id(pipeline_id))

    def state_path(self, pipeline_id: str) -> str:
        return os.path.join(self.pipeline_dir(pipeline_id), "state.json")

    def manifest_path(self, pipeline_id: str) -> str:
        return os.path.join(self.pipeline_dir(pipeline_id), "manifest.json")

    def artifacts_dir(self, pipeline_id: str) -> str:
        return os.path.join(self.pipeline_dir(pipeline_id), "artifacts")

    def save(self, state: DriverState) -> None:
        state.updated_at = utcnow()
        write_json_atomic(self.state_path(state.pipeline_id), state.to_dict())

    def load(self, pipeline_id: str) -> DriverState:
        path = self.state_path(pipeline_id)
        with open(path, encoding="utf-8") as f:
            import json
            data = json.load(f)
        version = int(data.get("schema_version") or 1)
        if version > SCHEMA_VERSION:
            raise IncompatibleStateSchema(pipeline_id, version)
        while version < SCHEMA_VERSION:
            migrate = _MIGRATIONS.get(version)
            if migrate is None:  # pragma: no cover — 缺失迁移属于开发期错误
                raise IncompatibleStateSchema(pipeline_id, version)
            data = migrate(data)
            version += 1
            data["schema_version"] = version
        return DriverState.from_dict(data)

    def exists(self, pipeline_id: str) -> bool:
        try:
            return os.path.exists(self.state_path(pipeline_id))
        except ValueError:
            return False
