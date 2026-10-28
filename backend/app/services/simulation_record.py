"""Simulation After-Action Record compiler (ADR 0003; design §3.1, §4).

Stage 5 finalization compiles ``simulation_record.json`` (schema
``simulation-record/v1``, shape in :mod:`simulation_record_contract`) and two
deterministic Markdown renderings (``simulation_record.md`` in the run's output
language, ``simulation_record.zh.md`` / the other language) from the simulation's
own artifacts.  Simulation output is a ``simulated`` record class: never
evidence, never a probability input (I-11).  Every reader-facing label comes
from :mod:`sim_provenance` or from this module's own bilingual label table.

Input contract (design §3.1, tested by T15):

* Only files inside the simulation directory are opened: ``world_state.json``,
  ``world_state_history.jsonl``, ``world_digest.jsonl``, ``world_actions.jsonl``,
  ``decisions.jsonl``, ``world_state_trajectory.json``, ``world_paths.json``,
  ``run_summary.json``, ``simulation_config.json`` (its ``temporal_config``,
  ``world_state_seed`` and ``output_language`` only), ``simulation_config_manifest.json``,
  ``state.json``, ``actor_cast_manifest.json`` and, for world-v1, the exported
  ``world_result.json`` / ``world_spec.json`` (read directly under the same
  containment, not through the world store).  The research dossier,
  ``sources.json``, the forecast spine, the market pack and ``forecast.json`` are
  never read.
* From ``world_actions.jsonl`` only :data:`simulation_record_contract.ACTION_PUBLIC_FIELDS`
  are kept; ``private_rationale`` is dropped at load time by allowlist.
* Scenario shares appear only under ``overall``; per-period sections carry none
  (herding guard I-1 applied to readers).

Generation modes (design §3.1): a deterministic skeleton always; one optional
bounded LLM synthesis (``Config.SIM_RECORD_SYNTHESIS``) that writes
``overall.synthesis.text`` from the skeleton only and is dropped, with the
reason recorded under ``limits.synthesis_dropped``, on any exception or any new
gate hard issue; a health stub (banner + health table + committed-period stubs,
no narrative, zero LLM calls) when ``run_summary.simulation_health`` is hollow,
errored or truncated or the decision-channel validity is not ``valid`` (I-16);
``llm_degraded`` keeps the skeleton and skips the synthesis call.

Three engine adapters produce the one schema: ``oasis-reflexive`` (full record
from ``world_state_history.jsonl``), ``world-v1`` (tables per period from
``world_result.json``; no arbiter narrative exists and the record says so) and
the thin ``oasis-inband`` / ``oasis-hours`` record from ``world_digest.jsonl``
whose banner line states that no world model ran.  Thin records are never padded.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import Config
from . import simulation_record_contract as rc

logger = logging.getLogger(__name__)

GENERATOR_VERSION = "simulation_record/1.0"

# Turning-point selection rule (design §3.3 item 2 applied to the record; fixed and tested):
# red-line crossings first, then offers accepted or breached, then the largest relative
# variable changes; ordered by round, then rule rank, then text; at most this many.
TURNING_POINT_CAP = 8
TURNING_POINT_VARIABLE_CHANGES = 3

# Period events taken from world_state.json (kind -> included); ``action`` rows duplicate the
# moves and ``offer`` / ``agreement`` / ``breach`` rows are rendered under offers.
_PERIOD_EVENT_KINDS = ("emergent", "consequence", "resolution", "system")
_OFFER_EVENT_KINDS = ("agreement", "breach")

_SYNTHESIS_MAX_PARAGRAPHS = 6
_SYNTHESIS_MAX_TOKENS = 900

# ── Bilingual label table (every reader-facing string of the record's own text) ──────────
_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "title": "Simulation After-Action Record",
        "subtitle": "Record class: simulated · epistemic status: elicited model projection",
        "engine": "Engine",
        "simulation": "Simulation",
        "as_of": "As of",
        "horizon": "Horizon",
        "calendar_unit": "calendar unit",
        "periods": "Periods committed / planned",
        "health": "Health",
        "validity": "Validity",
        "arbiter_failed": "arbiter-failed rounds",
        "seed_gaps": "modelling gaps",
        "organic": "organic actions",
        "setup": "Setup",
        "cast": "Cast",
        "agency_class": "class",
        "red_lines": "red lines",
        "documented_plans": "documented plans",
        "aliases": "aliases",
        "variables": "State variables (seed values)",
        "variable": "Variable",
        "seed_value": "Seed",
        "final_value": "Final",
        "unit": "Unit",
        "scenarios": "Scenarios",
        "shocks": "Seeded shocks",
        "no_shocks": "No exogenous shocks were seeded.",
        "modelling_gaps": "Modelling gaps reported by the seed",
        "period": "Period",
        "arbiter_status": "Arbiter status",
        "mechanical_only": "mechanical only — this round carries only the deterministic update",
        "arbiter_problems": "Arbiter problems",
        "narrative": "Arbiter narrative",
        "no_narrative": "No arbiter narrative was recorded for this period.",
        "stub_period": "Committed period; the record carries no narrative for this run (see the health line).",
        "moves": "Moves",
        "statement": "public statement",
        "commitment": "commitment",
        "due_periods": "due in periods",
        "terms": "terms",
        "held": "Held position",
        "facts": "Facts that changed",
        "from": "From",
        "to": "To",
        "cause": "Cause",
        "cause_unknown": "cause not recorded",
        "added": "variable added this period",
        "events": "Events",
        "shocks_fired": "Shocks fired",
        "offers": "Offers",
        "red_lines_crossed": "Red lines crossed",
        "by": "by",
        "alliances": "Alliance shifts",
        "behaviour": "Behaviour metrics",
        "behaviour_note": "The behaviour metric is a textual diagnostic, not a realism verdict.",
        "overall": "Overall",
        "final_vs_seed": "Final state versus seed",
        "unchanged_variables": "variables ended at their seed value",
        "shares": "Simulated outcome shares",
        "share": "share",
        "shares_caption": "Shares are elicited model projections of the simulated world; they are not probabilities and did not enter any probability.",
        "scenario": "Scenario",
        "final_share": "Final share",
        "mean_share": "Mean share",
        "paths": "paths",
        "leader": "leading scenario",
        "converged_at": "stabilised at round",
        "not_converged": "did not stabilise",
        "no_shares": "No scenario shares exist for this engine.",
        "turning_points": "Turning points",
        "tp_red_line": "red line crossed",
        "tp_offer": "offer",
        "tp_variable": "largest change",
        "no_turning_points": "No turning point met the fixed rule (red line crossed, offer accepted or breached, largest variable change).",
        "track_records": "Track records (commitments)",
        "kept": "kept",
        "lapsed": "lapsed",
        "broken": "broken",
        "released": "released",
        "open": "open",
        "no_track_records": "No commitment was resolved during the run.",
        "synthesis": "Synthesis",
        "generator": "generator",
        "limits": "Limits",
        "synthesis_dropped": "synthesis dropped",
        "no_world_model": "No world model ran in this simulation (engine: {engine}); this is the thin, digest-based account and it is not padded.",
        "world_v1_no_narrative": "The world-v1 engine records no arbiter narrative; period sections are tables of public events, offers and commitments.",
        "stub_sentence": "This run was not usable for narration (health: {health}; validity: {validity}). The record carries the health table and the committed periods only; no narrative was produced and no language model was called.",
        "digest": "digest",
        "effect_fired": "delayed effect fired",
        "commitment_lapsed": "commitment lapsed",
        "status": "status",
        "accepted": "accepted",
        "breached": "breached",
        "countered": "countered",
        "rejected": "rejected",
        "opened": "opened",
        "none": "none",
        "and": "and",
        "period_count_note": "{n} committed period(s) from {first} to {last}",
        "det_p1": "Over {span}, the leading simulated scenario at the end was “{leader}” with a final share of {share}. Shares moved most in the period {label}.",
        "det_p1_noshares": "Over {span}, no scenario shares were produced by this engine.",
        "det_p2_head": "Red lines crossed: {red}. Offers accepted: {accepted}. Offers breached: {breached}.",
        "det_p3_head": "What did not happen: scenarios that lost share against their seed — {losers}; offers that lapsed unanswered — {lapsed}; commitments that lapsed — {commitments}.",
        "det_p4_head": "Facts that moved most: {facts}.",
        "det_moved": "{name} from {a} to {b} {unit}",
        "no_items": "none",
        "rounds_mismatch": "world_state.json reports {a} committed rounds while the history carries {b}; the history is used.",
    },
    "zh": {
        "title": "情景模拟事后记录",
        "subtitle": "记录类别：模拟 · 认识论状态：模型推演投影",
        "engine": "引擎",
        "simulation": "模拟",
        "as_of": "基准日",
        "horizon": "判定日",
        "calendar_unit": "日历单位",
        "periods": "已提交／计划时段",
        "health": "健康状态",
        "validity": "有效性",
        "arbiter_failed": "仲裁失败轮次",
        "seed_gaps": "建模缺口",
        "organic": "有机动作",
        "setup": "设定",
        "cast": "角色阵容",
        "agency_class": "类别",
        "red_lines": "红线",
        "documented_plans": "已记载的计划",
        "aliases": "别名",
        "variables": "状态变量（种子值）",
        "variable": "变量",
        "seed_value": "种子值",
        "final_value": "终值",
        "unit": "单位",
        "scenarios": "情景",
        "shocks": "种子冲击",
        "no_shocks": "未播种任何外生冲击。",
        "modelling_gaps": "种子报告的建模缺口",
        "period": "时段",
        "arbiter_status": "仲裁状态",
        "mechanical_only": "仅机械推进——本轮只有确定性更新",
        "arbiter_problems": "仲裁问题",
        "narrative": "仲裁叙事",
        "no_narrative": "本时段没有记录仲裁叙事。",
        "stub_period": "已提交时段；本次运行不生成叙事（见健康状态行）。",
        "moves": "行动",
        "statement": "公开声明",
        "commitment": "承诺",
        "due_periods": "到期时段数",
        "terms": "条款",
        "held": "维持原状",
        "facts": "变化的事实",
        "from": "原值",
        "to": "新值",
        "cause": "原因",
        "cause_unknown": "未记录原因",
        "added": "本时段新增变量",
        "events": "事件",
        "shocks_fired": "触发的冲击",
        "offers": "要约",
        "red_lines_crossed": "越过的红线",
        "by": "由",
        "alliances": "结盟变化",
        "behaviour": "行为指标",
        "behaviour_note": "行为指标是文本层面的诊断，不是现实性判定。",
        "overall": "总体",
        "final_vs_seed": "终态对比种子",
        "unchanged_variables": "个变量停留在种子值",
        "shares": "模拟结果份额",
        "share": "份额",
        "shares_caption": "份额是模拟世界的模型推演投影；它们不是概率，也未进入任何概率。",
        "scenario": "情景",
        "final_share": "最终份额",
        "mean_share": "平均份额",
        "paths": "条路径",
        "leader": "领先情景",
        "converged_at": "趋稳轮次",
        "not_converged": "未趋稳",
        "no_shares": "该引擎不产生情景份额。",
        "turning_points": "转折点",
        "tp_red_line": "越过红线",
        "tp_offer": "要约",
        "tp_variable": "最大变动",
        "no_turning_points": "没有转折点满足固定规则（越过红线、要约被接受或违约、最大变量变动）。",
        "track_records": "履约记录（承诺）",
        "kept": "履行",
        "lapsed": "失效",
        "broken": "违背",
        "released": "解除",
        "open": "未决",
        "no_track_records": "运行期间没有承诺被判定。",
        "synthesis": "综述",
        "generator": "生成方式",
        "limits": "局限",
        "synthesis_dropped": "综述已弃用",
        "no_world_model": "本次模拟没有运行世界模型（引擎：{engine}）；这是基于摘要的精简记录，不作填充。",
        "world_v1_no_narrative": "world-v1 引擎不记录仲裁叙事；各时段为公开事件、要约与承诺的表格。",
        "stub_sentence": "本次运行不可用于叙事（健康状态：{health}；有效性：{validity}）。记录仅含健康状态表与已提交时段；未生成叙事，也未调用语言模型。",
        "digest": "摘要",
        "effect_fired": "延迟效应触发",
        "commitment_lapsed": "承诺失效",
        "status": "状态",
        "accepted": "已接受",
        "breached": "已违约",
        "countered": "已反要约",
        "rejected": "已拒绝",
        "opened": "已提出",
        "none": "无",
        "and": "与",
        "period_count_note": "自 {first} 至 {last} 的 {n} 个已提交时段",
        "det_p1": "在{span}内，结束时领先的模拟情景为「{leader}」，最终份额 {share}。份额变动最大的时段是 {label}。",
        "det_p1_noshares": "在{span}内，该引擎没有产生情景份额。",
        "det_p2_head": "越过的红线：{red}。被接受的要约：{accepted}。被违约的要约：{breached}。",
        "det_p3_head": "未发生的事：相对种子份额下降的情景——{losers}；无人回应而失效的要约——{lapsed}；失效的承诺——{commitments}。",
        "det_p4_head": "变动最大的事实：{facts}。",
        "det_moved": "{name} 由 {a} 变为 {b} {unit}",
        "no_items": "无",
        "rounds_mismatch": "world_state.json 报告 {a} 个已提交轮次，而历史记录含 {b} 个；以历史记录为准。",
    },
}

_ZH_LANGUAGE_MARKERS = ("zh", "chinese", "中文", "汉语", "汉文", "简体", "繁体", "mandarin")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class RecordBuildError(RuntimeError):
    """The simulation directory cannot be read as a record source."""


# ── small helpers ───────────────────────────────────────────────────────────────────────

def _labels(lang: str) -> Dict[str, str]:
    return _LABELS["zh" if lang == "zh" else "en"]


def _is_zh(name: Any) -> bool:
    text = str(name or "").strip().lower()
    return bool(text) and any(text.startswith(m) or m in text for m in _ZH_LANGUAGE_MARKERS)


def _text(value: Any, limit: int = 4000) -> str:
    out = str(value if value is not None else "").strip()
    return out if len(out) <= limit else out[:limit]


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fmt_number(value: Any, lang: str = "en") -> str:
    """Deterministic rendering of a JSON scalar for the Markdown tables."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return ("是" if value else "否") if lang == "zh" else ("true" if value else "false")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        try:
            dec = Decimal(repr(value))
            if abs(dec) >= Decimal("0.001"):
                # six decimals is the artifacts' own precision; this only removes float repr
                # noise such as 88.30000000000001 (the gate admits rounded variants of a value)
                dec = dec.quantize(Decimal("0.000001"))
            dec = dec.normalize()
        except InvalidOperation:
            return str(value)
        text = format(dec, "f")
        return text if text != "-0" else "0"
    return _text(value, 400)


def fmt_share(value: Any) -> str:
    """Scenario share rendered to one decimal of a percent (the gate compares after rounding)."""
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _list(value: Any) -> List[Any]:
    """A JSON list or [] — a string or scalar where a list was expected is not iterated."""
    return value if isinstance(value, list) else []


def _dedupe(items: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ── artifact reader (sim dir only) ──────────────────────────────────────────────────────

class _Artifacts:
    """Reads the simulation directory and nothing else; missing files are empty."""

    def __init__(self, sim_dir: str) -> None:
        if not sim_dir or not os.path.isdir(sim_dir):
            raise RecordBuildError(f"simulation directory does not exist: {sim_dir!r}")
        self.dir = os.path.realpath(sim_dir)
        self.errors: List[str] = []
        self.run_summary = self._json("run_summary.json")
        self.world_state = self._json("world_state.json")
        self.trajectory = self._json("world_state_trajectory.json")
        self.world_paths = self._json("world_paths.json")
        self.config_manifest = self._json("simulation_config_manifest.json")
        self.state = self._json("state.json")
        self.cast_manifest = self._json("actor_cast_manifest.json")
        config = self._json("simulation_config.json")
        # Only the calendar block, the seed block and the language are kept from the config;
        # agent personas and prompts are not record material.
        self.temporal = config.get("temporal_config") if isinstance(config.get("temporal_config"), dict) else {}
        self.world_seed = config.get("world_state_seed") if isinstance(config.get("world_state_seed"), dict) else {}
        self.output_language = _text(config.get("output_language"), 40)
        self.config_as_of = _text(config.get("as_of_date"), 20)
        self.history = self._jsonl("world_state_history.jsonl")
        self.actions = [self._public_action(r) for r in self._jsonl("world_actions.jsonl")]
        self.digest = self._jsonl("world_digest.jsonl")
        self.decisions = self._jsonl("decisions.jsonl")
        self.world_result: Dict[str, Any] = {}
        self.world_spec: Dict[str, Any] = {}

    # containment: a constant basename joined under the realpath'd directory; symlinks refused
    def path(self, name: str) -> Optional[str]:
        candidate = os.path.join(self.dir, name)
        if os.path.commonpath([os.path.realpath(candidate), self.dir]) != self.dir:
            return None
        if os.path.islink(candidate):
            self.errors.append(f"unsafe artifact: {name}")
            return None
        if not os.path.isfile(candidate):
            return None
        return candidate

    def exists(self, name: str) -> bool:
        return self.path(name) is not None

    def _json(self, name: str) -> Dict[str, Any]:
        path = self.path(name)
        if path is None:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            self.errors.append(f"unreadable artifact: {name}")
            return {}
        if not isinstance(data, dict):
            self.errors.append(f"invalid object: {name}")
            return {}
        return data

    def _jsonl(self, name: str) -> List[Dict[str, Any]]:
        path = self.path(name)
        if path is None:
            return []
        rows: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        self.errors.append(f"invalid row: {name}")
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
                    else:
                        self.errors.append(f"invalid row: {name}")
        except OSError:
            self.errors.append(f"unreadable artifact: {name}")
            return []
        return rows

    @staticmethod
    def _public_action(row: Dict[str, Any]) -> Dict[str, Any]:
        # Field allowlist, applied at load time: private_rationale never enters the record's memory.
        return {k: row[k] for k in rc.ACTION_PUBLIC_FIELDS if k in row}

    def load_world_v1(self) -> None:
        """world-v1: the exported result projection and the sealed spec, read under the same
        containment as every other artifact (regular files only, symlinks refused).  The
        export is written by ``results.export_result`` at completion; the record never opens
        the world store."""
        raw = self._json("world_result.json")
        self.world_result = rc.public_world_result(raw)
        if raw and raw.get("view") != "public":
            self.errors.append("world_result.json is not a public projection")
        self.world_spec = self._json("world_spec.json")

    @property
    def world(self) -> Dict[str, Any]:
        world = self.world_state.get("world")
        return world if isinstance(world, dict) else {}

    @property
    def world_summary(self) -> Dict[str, Any]:
        summary = self.world_state.get("summary")
        return summary if isinstance(summary, dict) else {}

    def committed_history(self) -> List[Dict[str, Any]]:
        """One row per committed round, in round order (the last write wins for a round)."""
        by_round: Dict[int, Dict[str, Any]] = {}
        for row in self.history:
            rnd = _as_int(row.get("round"))
            if rnd is None or rnd <= 0:
                continue
            # The world period commits even when the separate scenario-share
            # channel abstains/fails. Its status must not erase the period.
            by_round[rnd] = row
        return [by_round[r] for r in sorted(by_round)]


# ── resolution of engine, language, health ─────────────────────────────────────────────

def resolve_engine(art: _Artifacts, hint: Optional[str] = None) -> str:
    """Engine of the run: a contract value from the hint, else detected from the directory."""
    hint_text = str(hint or "").strip().lower()
    if hint_text == "world-v1" or art.state.get("simulation_engine") == "world-v1" \
            or art.exists("world_input_manifest.json") or art.exists("world_result.json"):
        return "world-v1"
    if hint_text in ("oasis-reflexive", "oasis-inband", "oasis-hours"):
        return hint_text
    if art.committed_history() or art.world_state or art.exists("world_state_history.jsonl"):
        return "oasis-reflexive"
    mode = str(art.temporal.get("mode") or art.trajectory.get("mode") or "").lower()
    if mode == "calendar" or art.digest:
        return "oasis-inband"
    return "oasis-hours"


def resolve_language(art: _Artifacts, language: Optional[str] = None) -> str:
    """``"zh"`` or ``"en"``: the explicit run language, else the sealed config's output language,
    else the CJK share of the arbiter narratives / digests."""
    for candidate in (language, art.output_language):
        text = str(candidate or "").strip()
        if text:
            return "zh" if _is_zh(text) else "en"
    sample = " ".join(_text(r.get("narrative"), 2000) for r in art.history[:6])
    if not sample.strip():
        sample = " ".join(_text(r.get("digest"), 2000) for r in art.digest[:6])
    if sample.strip() and len(_CJK_RE.findall(sample)) > max(1, len(sample)) * 0.05:
        return "zh"
    return "en"


def decision_channel_validity(trajectory: Dict[str, Any]) -> str:
    """The run-level validity verdict (``decision_channel.py``: valid / inconclusive / invalid).

    The trajectory writer stores ``outcome.round_accounting``; when no explicit ``validity``
    key exists the verdict is derived with the frozen convergence policy, exactly as
    ``decision_channel`` derives it.  ``"unknown"`` when no trajectory exists.
    """
    if not isinstance(trajectory, dict) or not trajectory:
        return "unknown"
    explicit = trajectory.get("validity")
    if isinstance(explicit, str) and explicit in ("valid", "inconclusive", "invalid"):
        return explicit
    outcome = trajectory.get("outcome") if isinstance(trajectory.get("outcome"), dict) else {}
    accounting = outcome.get("round_accounting") if isinstance(outcome.get("round_accounting"), dict) else \
        trajectory.get("round_accounting") if isinstance(trajectory.get("round_accounting"), dict) else None
    if not accounting:
        return "unknown"
    from .worldstate import CONVERGENCE_POLICY_V1
    try:
        valid_transitions = int(accounting.get("valid_transitions") or 0)
        failed_rounds = int(accounting.get("failed_rounds") or 0)
        coverage = float(accounting.get("valid_coverage") or 0.0)
    except (TypeError, ValueError):
        return "unknown"
    if valid_transitions <= 0:
        return "invalid"
    if failed_rounds > 0 or coverage < float(CONVERGENCE_POLICY_V1["min_valid_coverage"]):
        return "inconclusive"
    return "valid"


# ── reflexive adapter ───────────────────────────────────────────────────────────────────

def _actor_names(art: _Artifacts) -> Tuple[List[str], List[str]]:
    """(cast names, aliases) from world_state.json, the cast manifest and the action rows."""
    names: List[str] = []
    aliases: List[str] = []
    for actor in _list(art.world.get("actors")):
        if isinstance(actor, dict):
            names.append(_text(actor.get("name"), 160))
            aliases.extend(_text(a, 160) for a in _list(actor.get("aliases")) if _text(a, 160))
    for decision in _list(art.cast_manifest.get("decisions")):
        if isinstance(decision, dict) and decision.get("status") == "selected":
            names.append(_text(decision.get("actor_name"), 160))
    for name in _list(art.cast_manifest.get("selected_actor_names")):
        names.append(_text(name, 160))
    for action in art.actions:
        names.append(_text(action.get("actor_name"), 160))
    return _dedupe(names), _dedupe(aliases)


def _variable_causes(art: _Artifacts) -> Dict[Tuple[str, int], List[str]]:
    causes: Dict[Tuple[str, int], List[str]] = {}
    for var in _list(art.world.get("variables")):
        if not isinstance(var, dict):
            continue
        vid = _text(var.get("id"), 120)
        for entry in _list(var.get("history")):
            if not isinstance(entry, dict):
                continue
            rnd = _as_int(entry.get("round"))
            cause = _text(entry.get("cause"), 600)
            if rnd is None or not cause:
                continue
            bucket = causes.setdefault((vid, rnd), [])
            if cause not in bucket:
                bucket.append(cause)
    return causes


def _events_by_round(art: _Artifacts) -> Dict[int, List[Tuple[int, Dict[str, Any]]]]:
    grouped: Dict[int, List[Tuple[int, Dict[str, Any]]]] = {}
    counters: Dict[int, int] = {}
    for event in _list(art.world.get("events")):
        if not isinstance(event, dict):
            continue
        rnd = _as_int(event.get("round"))
        if rnd is None:
            continue
        idx = counters.get(rnd, 0)
        counters[rnd] = idx + 1
        grouped.setdefault(rnd, []).append((idx, event))
    return grouped


def _interaction_terms(art: _Artifacts) -> Dict[str, Dict[str, Any]]:
    return {_text(i.get("id"), 80): i for i in _list(art.world.get("interactions")) if isinstance(i, dict)}


def _history_ref(rnd: int) -> Dict[str, Any]:
    return {"file": "world_state_history.jsonl", "round": rnd, "id": f"round:{rnd}"}


def _period_frame(row: Dict[str, Any], rnd: int, lang: str) -> Dict[str, Any]:
    period = row.get("period") if isinstance(row.get("period"), dict) else {}
    label = _text(row.get("period_label") or period.get("label"), 80) or f"round {rnd}"
    status = _text(row.get("arbiter_status"), 40) or "skipped"
    problems = row.get("arbiter_problems") if isinstance(row.get("arbiter_problems"), list) else []
    return {
        "round": rnd,
        "label": label,
        "period_start": _text(period.get("period_start"), 40) or None,
        "period_end": _text(period.get("period_end"), 40) or None,
        "arbiter_status": status,
        "arbiter_problems": [_text(p, 600) for p in problems[:12]],
        "mechanical_only": status != "applied",
        "narrative": "",
        "moves": [],
        "held_position": [],
        "facts_changed": [],
        "events": [],
        "shocks_fired": [],
        "red_lines_crossed": [],
        "offers": [],
        "alliances": [],
        "behaviour": {},
        "refs": [_history_ref(rnd)],
    }


def _periods_reflexive(art: _Artifacts, lang: str, *, stub: bool) -> List[Dict[str, Any]]:
    L = _labels(lang)
    rows = art.committed_history()
    actions_by_round: Dict[int, List[Dict[str, Any]]] = {}
    for action in art.actions:
        rnd = _as_int(action.get("round"))
        if rnd is not None:
            actions_by_round.setdefault(rnd, []).append(action)
    causes = _variable_causes(art)
    events = _events_by_round(art)
    interactions = _interaction_terms(art)
    periods: List[Dict[str, Any]] = []
    for row in rows:
        rnd = int(row["round"])
        section = _period_frame(row, rnd, lang)
        if stub:
            section["stub"] = True
            periods.append(section)
            continue
        section["narrative"] = _text(row.get("narrative"), 8000)
        # moves and held positions: public fields only (ACTION_PUBLIC_FIELDS)
        for action in actions_by_round.get(rnd, []):
            if action.get("status") != "ok":
                continue
            option = action.get("option") if isinstance(action.get("option"), dict) else {}
            actor = _text(action.get("actor_name"), 160)
            if option.get("id") == "hold_position" or option.get("kind") == "wait":
                section["held_position"].append(actor)
                continue
            commitment = action.get("commitment") if isinstance(action.get("commitment"), dict) else None
            move: Dict[str, Any] = {
                "actor": actor,
                "option": _text(option.get("label") or option.get("id"), 300),
                "kind": _text(option.get("kind"), 40) or None,
                "targets": [_text(t, 160) for t in _list(action.get("targets")) if _text(t, 160)],
                "magnitude": action.get("magnitude") if _is_number(action.get("magnitude")) else None,
                "public_statement": _text(action.get("public_statement"), 4000),
                "terms": _text(action.get("terms"), 2000) or None,
                "commitment": ({"text": _text(commitment.get("description"), 600),
                                "due_periods": _as_int(commitment.get("due_periods"))}
                               if commitment else None),
                "ref": {"file": "world_actions.jsonl", "round": rnd, "id": f"agent:{action.get('agent_id')}"},
            }
            section["moves"].append(move)
            for shift in _list(action.get("alliance_moves")):
                if isinstance(shift, dict) and _text(shift.get("target"), 160):
                    section["alliances"].append({
                        "kind": "alliance_move", "actor": actor,
                        "move": _text(shift.get("move"), 40), "target": _text(shift.get("target"), 160),
                        "ref": move["ref"],
                    })
        # facts changed: the row's diff, causes from the variable histories
        diff = row.get("diff") if isinstance(row.get("diff"), dict) else {}
        for change in _list(diff.get("variables_changed")):
            if not isinstance(change, dict):
                continue
            vid = _text(change.get("id"), 120)
            section["facts_changed"].append({
                "variable": _text(change.get("name") or vid, 200),
                "from": change.get("from"), "to": change.get("to"),
                "unit": _text(change.get("unit"), 60),
                "cause": "; ".join(causes.get((vid, rnd), [])) or L["cause_unknown"],
                "ref": {"file": "world_state.json", "round": rnd, "id": f"var:{vid}"},
            })
        for added in _list(diff.get("variables_added")):
            if not isinstance(added, dict):
                continue
            vid = _text(added.get("id"), 120)
            section["facts_changed"].append({
                "variable": _text(added.get("name") or vid, 200),
                "from": None, "to": added.get("value"),
                "unit": _text(added.get("unit"), 60),
                "cause": "; ".join(causes.get((vid, rnd), [])) or L["added"],
                "ref": {"file": "world_state.json", "round": rnd, "id": f"var:{vid}"},
            })
        # events, delayed effects, lapsed commitments, shocks
        offer_events: Dict[str, str] = {}
        for idx, event in events.get(rnd, []):
            kind = _text(event.get("kind"), 40)
            description = _text(event.get("description"), 1200)
            ref = {"file": "world_state.json", "round": rnd, "id": f"event:{rnd}:{idx}"}
            if kind in _PERIOD_EVENT_KINDS:
                section["events"].append({
                    "kind": kind, "text": description,
                    "actors": [_text(a, 160) for a in _list(event.get("actors"))[:4]],
                    "ref": ref,
                })
            elif kind in _OFFER_EVENT_KINDS:
                match = re.search(r"\[(i\d+_\d+)\]", description)
                if match:
                    offer_events[match.group(1)] = description
        deterministic = row.get("deterministic") if isinstance(row.get("deterministic"), dict) else {}
        for fired in _list(deterministic.get("effects_fired")):
            text = _text(fired.get("description") if isinstance(fired, dict) else fired, 600)
            if text:
                section["events"].append({"kind": "effect_fired", "text": text, "actors": [], "ref": _history_ref(rnd)})
        for lapsed in _list(deterministic.get("commitments_lapsed")):
            text = _text(lapsed, 600)
            if text:
                section["events"].append({"kind": "commitment_lapsed", "text": text, "actors": [], "ref": _history_ref(rnd)})
        for shock in _list(deterministic.get("shocks_fired")):
            if isinstance(shock, dict):
                text = _text(shock.get("event") or shock.get("name") or shock.get("id"), 400)
            else:
                text = _text(shock, 400)
            if text:
                section["shocks_fired"].append(text)
        # offers by status: the row's interaction diff
        for change in _list(diff.get("interactions_changed")):
            if not isinstance(change, dict):
                continue
            iid = _text(change.get("id"), 80)
            status = _text(change.get("to"), 40) or "opened"
            stored = interactions.get(iid, {})
            section["offers"].append({
                "id": iid,
                "from_actor": _text(change.get("proposer"), 160),
                "to_actor": _text(change.get("recipient"), 160),
                "kind": _text(change.get("kind"), 40),
                "status": "opened" if status == "open" else status,
                "previous": _text(change.get("from"), 40) or None,
                "terms": _text(change.get("terms") or stored.get("terms"), 1200),
                "event": offer_events.get(iid),
                "ref": {"file": "world_state.json", "round": rnd, "id": f"interaction:{iid}"},
            })
        # red lines and relationship shifts (arbiter apply summary / diff)
        arbiter = row.get("arbiter") if isinstance(row.get("arbiter"), dict) else {}
        for crossed in _list(arbiter.get("red_lines_crossed")):
            if isinstance(crossed, dict):
                section["red_lines_crossed"].append({
                    "actor": _text(crossed.get("actor"), 160), "by": _text(crossed.get("by"), 160),
                    "red_line": _text(crossed.get("red_line"), 400),
                })
            elif _text(crossed, 400):
                section["red_lines_crossed"].append({"actor": "", "by": "", "red_line": _text(crossed, 400)})
        for rel in _list(diff.get("relationships_changed")):
            if not isinstance(rel, dict):
                continue
            before, after = rel.get("from"), rel.get("to")
            if before is None or after is None or before == after:
                continue
            section["alliances"].append({
                "kind": "relationship", "source": _text(rel.get("source"), 160),
                "target": _text(rel.get("target"), 160), "from": _text(before, 40), "to": _text(after, 40),
                "direction": _text(rel.get("direction"), 40) or None, "ref": _history_ref(rnd),
            })
        behaviour = row.get("behaviour") if isinstance(row.get("behaviour"), dict) else {}
        decisions = row.get("decisions") if isinstance(row.get("decisions"), dict) else {}
        section["behaviour"] = {
            **{k: v for k, v in behaviour.items() if _is_number(v) or v is None},
            "moves": behaviour.get("moves") if _is_number(behaviour.get("moves")) else len(section["moves"]),
            "held": len(section["held_position"]),
            "decisions_total": _as_int(decisions.get("total")),
        }
        periods.append(section)
    return periods


def _setup_reflexive(art: _Artifacts, lang: str) -> Dict[str, Any]:
    cast: List[Dict[str, Any]] = []
    for actor in _list(art.world.get("actors")):
        if not isinstance(actor, dict):
            continue
        cast.append({
            "actor": _text(actor.get("name"), 160),
            "agency_class": _text(actor.get("agency_class"), 60),
            "aliases": [_text(a, 160) for a in _list(actor.get("aliases")) if _text(a, 160)],
            "red_lines": [_text(r, 300) for r in _list(actor.get("red_lines")) if _text(r, 300)],
            "documented_plans": [_text(p, 300) for p in _list(actor.get("documented_plans")) if _text(p, 300)],
        })
    variables: List[Dict[str, Any]] = []
    for var in _list(art.world.get("variables")):
        if not isinstance(var, dict):
            continue
        history = [h for h in _list(var.get("history")) if isinstance(h, dict)]
        seed = history[0].get("value") if history else var.get("value")
        variables.append({
            "id": _text(var.get("id"), 120), "name": _text(var.get("name"), 200),
            "seed_value": seed, "unit": _text(var.get("unit"), 60), "kind": _text(var.get("kind"), 20),
            "as_of": _text(var.get("as_of"), 20) or None, "provenance": _text(var.get("provenance"), 40) or None,
        })
    scenarios = [_text(s, 200) for s in _list(art.world.get("scenarios") or art.world_seed.get("scenarios")
                                               or art.trajectory.get("scenarios")) if _text(s, 200)]
    shocks: List[Dict[str, Any]] = []
    for shock in _list(art.world.get("shocks")):
        if isinstance(shock, dict):
            shocks.append({"name": _text(shock.get("event") or shock.get("name") or shock.get("id"), 300),
                           "base_rate": _text(shock.get("base_rate_text") or shock.get("base_rate"), 80) or None,
                           "window": _text(shock.get("window"), 80) or None,
                           "fired_rounds": [r for r in _list(shock.get("fired_rounds")) if _as_int(r) is not None]})
    gaps: List[str] = []
    for gap in _list(art.world.get("seed_gaps")):
        if isinstance(gap, dict):
            gaps.append(": ".join(x for x in (_text(gap.get("kind"), 80), _text(gap.get("subject"), 160)) if x)
                        + (f" — {_text(gap.get('note'), 300)}" if _text(gap.get("note"), 300) else ""))
        elif _text(gap, 400):
            gaps.append(_text(gap, 400))
    return {"cast": cast, "variables": variables, "scenarios": scenarios, "shocks": shocks, "seed_gaps": gaps}


def _paths_block(art: _Artifacts, scenarios: Sequence[str]) -> Dict[str, Any]:
    """Per-scenario share distribution across the K world paths (world_state summary first,
    else recomputed from world_paths.json with the engine's own distribution helper)."""
    summary_paths = art.world_summary.get("paths") if isinstance(art.world_summary.get("paths"), dict) else {}
    if summary_paths:
        per_scenario = {}
        for name, stats in (summary_paths.get("shares") or {}).items():
            if isinstance(stats, dict):
                per_scenario[str(name)] = {k: stats.get(k) for k in ("mean", "sd", "p10", "p50", "p90") if k in stats}
        per_path = []
        for row in _list(summary_paths.get("per_path")):
            if isinstance(row, dict):
                per_path.append({"path": row.get("path"), "leader": row.get("leader"),
                                 "arbiter_failed_rounds": row.get("arbiter_failed_rounds"),
                                 "shocks_fired": [str(s) for s in _list(row.get("shocks_fired"))]})
        return {"k": _as_int(summary_paths.get("k")) or 1, "per_scenario": per_scenario,
                "leaders": dict(summary_paths.get("leaders") or {}), "per_path": per_path}
    paths = art.world_paths.get("paths") if isinstance(art.world_paths.get("paths"), list) else []
    if paths:
        from .world_paths import share_distribution
        per_path_shares = [p.get("shares") for p in paths if isinstance(p, dict) and isinstance(p.get("shares"), dict)]
        dist = share_distribution(per_path_shares, list(scenarios))
        per_scenario = {name: {k: stats.get(k) for k in ("mean", "sd", "p10", "p50", "p90")}
                        for name, stats in (dist.get("shares") or {}).items() if isinstance(stats, dict)}
        per_path = []
        for p in paths:
            if not isinstance(p, dict):
                continue
            world = p.get("world") if isinstance(p.get("world"), dict) else {}
            fired = [_text(s.get("id"), 80) for s in _list(world.get("shocks"))
                     if isinstance(s, dict) and s.get("fired_rounds")]
            per_path.append({"path": p.get("path"), "arbiter_failed_rounds": p.get("arbiter_failed_rounds"),
                             "shocks_fired": fired})
        return {"k": _as_int(art.world_paths.get("k")) or len(per_path_shares) or 1,
                "per_scenario": per_scenario, "leaders": dict(dist.get("leaders") or {}), "per_path": per_path}
    return {"k": 1}


def _shares_block(art: _Artifacts, scenarios: Sequence[str]) -> Dict[str, Any]:
    outcome = art.trajectory.get("outcome") if isinstance(art.trajectory.get("outcome"), dict) else {}
    final = outcome.get("shares") if isinstance(outcome.get("shares"), dict) else art.world.get("scenario_shares")
    if not isinstance(final, dict) or not final:
        return {}
    converged = art.trajectory.get("converged_at")
    if converged is None and isinstance(outcome, dict):
        converged = outcome.get("converged_at")
    block = {
        "epistemic_status": rc.EPISTEMIC_STATUS,
        "final": {str(k): v for k, v in final.items() if _is_number(v)},
        "leader": _text(outcome.get("leader"), 200) or None,
        "converged_at": _as_int(converged),
        "paths": _paths_block(art, scenarios),
    }
    for key in ("share_prior", "share_source", "share_source_reason", "share_update_reason"):
        value = outcome.get(key, art.world_seed.get(key))
        if isinstance(value, str) and value:
            block[key] = _text(value, 160)
    return block


def share_policy_note(shares: Dict[str, Any], lang: str = "en") -> str:
    """Reader-facing policy note, shared with the deterministic report bridge.

    Unconfigured historical records return no new text. Probabilities and raw
    actor messages are never read here; only bounded reducer provenance is used.
    """
    zh = str(lang).lower().startswith(("zh", "chinese", "mandarin"))
    parts = []
    prior = shares.get("share_prior")
    if prior == "uniform":
        parts.append("份额从均匀分布开始；未使用研究先验。" if zh else
                     "Shares started uniform; the research prior was not used.")
    elif prior == "research":
        parts.append("份额使用研究先验初始化（回滚模式）。" if zh else
                     "Shares started from the research prior (rollback mode).")
    source = shares.get("share_source")
    descriptions = {
        "votes": ("Source: legacy actor votes (rollback mode).", "来源：旧版行动者投票（回滚模式）。"),
        "power_votes": ("Source: declared outcome power weighted by resolved actions.", "来源：已声明的结果影响力，按行动裁决加权。"),
        "predicates": ("Source: typed target outcomes classified by scenario predicates.", "来源：按情景条件分类的类型化目标结果。"),
    }
    if source in descriptions:
        parts.append(descriptions[source][int(zh)])
    if source == "power_votes" and shares.get("share_source_reason") in {
            "missing_forecast_case", "missing_target_identity", "invalid_target_predicates", "private_target_unavailable"}:
        parts.append("没有可用的已验证目标条件，因此采用影响力加权。" if zh else
                     "Declared power was selected because validated target predicates were unavailable.")
    reasons = {
        "unknown_power": ("Shares froze because outcome power was unknown.", "结果影响力未知，份额保持不变。"),
        "unknown_resolution": ("Shares froze because action resolution was unavailable.", "缺少行动裁决，份额保持不变。"),
        "zero_effect": ("Shares froze because resolved actions had zero effective weight.", "裁决后的行动有效权重为零，份额保持不变。"),
        "target_unavailable": ("Shares froze because the target outcome was unavailable.", "目标结果不可用，份额保持不变。"),
        "target_outside_scenario_partition": ("Shares froze because target outcomes did not fit the scenario partition.", "目标结果不符合情景划分，份额保持不变。"),
        "invalid_target_predicates": ("Shares froze because target predicates were invalid or absent.", "目标情景条件无效或缺失，份额保持不变。"),
        "invalid_round_status": ("Shares froze because this round lacked a valid action signal.", "本轮缺少有效行动信号，份额保持不变。"),
        "no_eligible_decisions": ("Shares froze because no eligible decisions were available.", "没有合格的决策，份额保持不变。"),
        "invalid_decision": ("Shares froze because decision values were invalid.", "决策数值无效，份额保持不变。"),
        "invalid_total_power": ("Shares froze because total effective power was not finite.", "有效影响力总量不是有限值，份额保持不变。"),
    }
    reason = shares.get("share_update_reason")
    if reason in reasons:
        parts.append(reasons[reason][int(zh)])
    return " ".join(parts)


def _final_variables(art: _Artifacts) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for var in _list(art.world.get("variables")):
        if not isinstance(var, dict):
            continue
        history = [h for h in _list(var.get("history")) if isinstance(h, dict)]
        seed = history[0].get("value") if history else None
        final = var.get("value")
        out.append({"id": _text(var.get("id"), 120), "name": _text(var.get("name"), 200),
                    "seed_value": seed, "final_value": final, "unit": _text(var.get("unit"), 60),
                    "changed": seed != final})
    return out


def _track_records(art: _Artifacts) -> List[Dict[str, Any]]:
    """Per-actor commitment outcomes with ``ActorState.track_record``'s status mapping."""
    mapping = {"fulfilled": "kept", "lapsed": "lapsed", "breached": "broken", "released": "released"}
    out: List[Dict[str, Any]] = []
    for actor in _list(art.world.get("actors")):
        if not isinstance(actor, dict):
            continue
        counts = {"kept": 0, "lapsed": 0, "broken": 0, "released": 0, "open": 0}
        commitments = [c for c in _list(actor.get("commitments")) if isinstance(c, dict)]
        if not commitments:
            continue
        for c in commitments:
            counts[mapping.get(str(c.get("status") or ""), "open")] += 1
        out.append({"actor": _text(actor.get("name"), 160), **counts,
                    "resolved": counts["kept"] + counts["lapsed"] + counts["broken"]})
    out.sort(key=lambda r: r["actor"])
    return out


def _turning_points(periods: Sequence[Dict[str, Any]], lang: str) -> List[Dict[str, Any]]:
    """Fixed rule: red-line crossings (rank 0), offers accepted or breached (rank 1), the
    TURNING_POINT_VARIABLE_CHANGES largest relative variable changes over the run (rank 2);
    ordered by round, rank, text; capped at TURNING_POINT_CAP."""
    L = _labels(lang)
    candidates: List[Tuple[int, int, str, Dict[str, Any]]] = []
    changes: List[Tuple[float, int, Dict[str, Any]]] = []
    for section in periods:
        rnd = int(section["round"])
        for crossed in section.get("red_lines_crossed") or []:
            who = crossed.get("actor") or ""
            by = f" ({L['by']} {crossed['by']})" if crossed.get("by") else ""
            why = f"{L['tp_red_line']}: {who} — {crossed.get('red_line', '')}{by}".strip()
            candidates.append((rnd, 0, why, {"round": rnd, "why": why, "ref": section["refs"][0]}))
        for offer in section.get("offers") or []:
            if offer.get("status") in ("accepted", "breached"):
                why = f"{L['tp_offer']} {L[offer['status']]}: {offer.get('from_actor', '')} → {offer.get('to_actor', '')}"
                candidates.append((rnd, 1, why, {"round": rnd, "why": why, "ref": offer["ref"]}))
        for fact in section.get("facts_changed") or []:
            a, b = fact.get("from"), fact.get("to")
            if isinstance(a, bool) or isinstance(b, bool):
                continue
            try:
                before, after = Decimal(str(a)), Decimal(str(b))
            except InvalidOperation:
                continue
            if before.is_finite() and after.is_finite() and before != after:
                rel = abs(after - before) / max(abs(before), Decimal("1e-9"))
                changes.append((rel, rnd, fact))
    changes.sort(key=lambda c: (-c[0], c[1], str(c[2].get("variable"))))
    for _rel, rnd, fact in changes[:TURNING_POINT_VARIABLE_CHANGES]:
        why = f"{L['tp_variable']}: " + L["det_moved"].format(
            name=fact.get("variable"), a=fmt_number(fact.get("from"), lang), b=fmt_number(fact.get("to"), lang),
            unit=fact.get("unit") or "").strip()
        candidates.append((rnd, 2, why, {"round": rnd, "why": why, "ref": fact["ref"]}))
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    return [c[3] for c in candidates[:TURNING_POINT_CAP]]


# ── world-v1 adapter ────────────────────────────────────────────────────────────────────

def _world_v1_actor_names(art: _Artifacts) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for actor in _list(art.world_spec.get("actors")):
        if isinstance(actor, dict) and actor.get("actorId"):
            names[str(actor["actorId"])] = _text(actor.get("name") or actor["actorId"], 160)
    return names


def _world_v1_periods(art: _Artifacts, lang: str, *, stub: bool) -> List[Dict[str, Any]]:
    result = art.world_result
    names = _world_v1_actor_names(art)
    committed = _as_int(result.get("committedRound")) or 0
    trajectory = [row for row in _list(result.get("trajectory")) if isinstance(row, dict)]
    by_round = {_as_int(row.get("round")): row for row in trajectory if _as_int(row.get("round")) is not None}
    spec_periods = [p for p in _list(art.world_spec.get("periods")) if isinstance(p, dict)]
    events: Dict[int, List[Dict[str, Any]]] = {}
    for event in _list(result.get("events")):
        if isinstance(event, dict) and _as_int(event.get("round")) is not None:
            events.setdefault(int(event["round"]), []).append(event)
    periods: List[Dict[str, Any]] = []
    for rnd in sorted(r for r in by_round if 0 < r <= committed):
        row = by_round.get(rnd, {})
        spec_period = spec_periods[rnd - 1] if rnd - 1 < len(spec_periods) else {}
        at = _text(row.get("simulatedAt"), 40)
        label = at[:10] if at else (_text(spec_period.get("end"), 40)[:10] or f"round {rnd}")
        section = {
            "round": rnd, "label": label,
            "period_start": _text(spec_period.get("start"), 40)[:10] or None,
            "period_end": _text(spec_period.get("end"), 40)[:10] or (at[:10] or None),
            "arbiter_status": "not_applicable", "arbiter_problems": [], "mechanical_only": False,
            "narrative": "", "moves": [], "held_position": [], "facts_changed": [], "events": [],
            "shocks_fired": [], "red_lines_crossed": [], "offers": [], "alliances": [], "behaviour": {},
            "refs": [{"file": "world_result.json", "round": rnd, "id": f"round:{rnd}"}],
        }
        if stub:
            section["stub"] = True
            periods.append(section)
            continue
        previous = by_round.get(rnd - 1, {})
        interactions = row.get("interactions", {})
        commitments = row.get("commitments", {})
        previous_interactions = previous.get("interactions", {})
        previous_commitments = previous.get("commitments", {})
        for bucket in ("metrics", "rules"):
            now_values = row.get(bucket) if isinstance(row.get(bucket), dict) else {}
            before_values = previous.get(bucket) if isinstance(previous.get(bucket), dict) else {}
            for key in sorted(now_values):
                after_rec = now_values.get(key) if isinstance(now_values.get(key), dict) else {}
                before_rec = before_values.get(key) if isinstance(before_values.get(key), dict) else {}
                if after_rec.get("value") != before_rec.get("value") and before_rec:
                    section["facts_changed"].append({
                        "variable": str(key), "from": before_rec.get("value"), "to": after_rec.get("value"),
                        "unit": _text(after_rec.get("unit"), 60), "cause": "kernel",
                        "ref": {"file": "world_result.json", "round": rnd, "id": f"{bucket}:{key}"},
                    })
        for event in events.get(rnd, []):
            actor = names.get(str(event.get("actorId") or ""), _text(event.get("actorId"), 80))
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            detail_text = ", ".join(f"{k}={fmt_number(v, lang)}" for k, v in sorted(details.items())
                                    if isinstance(v, (str, int, float)) and not isinstance(v, bool))
            text = _text(event.get("description"), 400) + (f" ({detail_text})" if detail_text else "")
            section["events"].append({"kind": _text(event.get("kind"), 60), "text": text,
                                      "actors": [actor] if actor else [],
                                      "ref": {"file": "world_result.json", "round": rnd,
                                              "id": _text(event.get("eventId"), 160) or f"round:{rnd}"}})
        for iid, inter in sorted(interactions.items()):
            if not isinstance(inter, dict):
                continue
            before = previous_interactions.get(iid, {})
            if before and all(before.get(k) == inter.get(k) for k in ("status", "terms")):
                continue
            recipients = [names.get(str(r), str(r)) for r in _list(inter.get("recipientIds"))]
            if inter.get("kind") == "message":
                section["events"].append({
                    "kind": "message", "actors": [names.get(str(inter.get("proposerId")), ""), *recipients],
                    "text": _text(json.dumps(inter.get("terms"), ensure_ascii=False, sort_keys=True), 600),
                    "ref": {"file": "world_result.json", "round": rnd, "id": str(iid)},
                })
                continue
            section["offers"].append({
                "id": str(iid), "from_actor": names.get(str(inter.get("proposerId")), _text(inter.get("proposerId"), 80)),
                "to_actor": ", ".join(recipients), "kind": _text(inter.get("templateId"), 80),
                "status": _text(inter.get("status"), 40), "previous": before.get("status"),
                "terms": _text(json.dumps(inter.get("terms"), ensure_ascii=False, sort_keys=True)
                               if isinstance(inter.get("terms"), (dict, list)) else inter.get("terms"), 600),
                "event": None,
                "ref": {"file": "world_result.json", "round": rnd, "id": str(iid)},
            })
        for cid, com in sorted(commitments.items()):
            if not isinstance(com, dict):
                continue
            before = previous_commitments.get(cid, {})
            if not before or before.get("status") != com.get("status"):
                actor = names.get(str(com.get("actorId")), _text(com.get("actorId"), 80))
                section["events"].append({"kind": "commitment", "actors": [actor],
                                          "text": f"{actor}: {_text(com.get('kind'), 60)} ({_text(com.get('status'), 40)})",
                                          "ref": {"file": "world_result.json", "round": rnd, "id": str(cid)}})
        section["behaviour"] = {"events": len(section["events"]), "offers": len(section["offers"])}
        periods.append(section)
    return periods


def _world_v1_overall(art: _Artifacts, periods: Sequence[Dict[str, Any]], lang: str) -> Dict[str, Any]:
    result = art.world_result
    names = _world_v1_actor_names(art)
    trajectory = [row for row in _list(result.get("trajectory")) if isinstance(row, dict)]
    first = trajectory[0] if trajectory else {}
    world = result.get("world") if isinstance(result.get("world"), dict) else {}
    final_variables = []
    for bucket in ("metrics", "rules"):
        now_values = world.get(bucket) if isinstance(world.get(bucket), dict) else {}
        seed_values = first.get(bucket) if isinstance(first.get(bucket), dict) else {}
        for key in sorted(now_values):
            rec = now_values[key] if isinstance(now_values[key], dict) else {}
            seed = seed_values.get(key, {}).get("value") if isinstance(seed_values.get(key), dict) else None
            final_variables.append({"id": f"{bucket}:{key}", "name": str(key), "seed_value": seed,
                                    "final_value": rec.get("value"), "unit": _text(rec.get("unit"), 60),
                                    "changed": seed != rec.get("value")})
    mapping = {"fulfilled": "kept", "settled": "kept", "lapsed": "lapsed", "expired": "lapsed",
               "breached": "broken", "broken": "broken", "released": "released"}
    records: Dict[str, Dict[str, int]] = {}
    commitments = world.get("commitments") if isinstance(world.get("commitments"), dict) else {}
    for com in commitments.values():
        if not isinstance(com, dict):
            continue
        actor = names.get(str(com.get("actorId")), _text(com.get("actorId"), 80))
        counts = records.setdefault(actor, {"kept": 0, "lapsed": 0, "broken": 0, "released": 0, "open": 0})
        counts[mapping.get(str(com.get("status") or ""), "open")] += 1
    track = [{"actor": a, **c, "resolved": c["kept"] + c["lapsed"] + c["broken"]} for a, c in sorted(records.items())]
    return {"final_variables": final_variables, "shares": {}, "turning_points": _turning_points(periods, lang),
            "track_records": track}


# ── thin adapter (in-band / hours) ──────────────────────────────────────────────────────

def _periods_thin(art: _Artifacts, *, stub: bool) -> List[Dict[str, Any]]:
    by_round: Dict[int, Dict[str, Any]] = {}
    for row in art.digest:
        rnd = _as_int(row.get("round"))
        if rnd is not None and rnd > 0:
            by_round[rnd] = row
    periods: List[Dict[str, Any]] = []
    for rnd in sorted(by_round):
        row = by_round[rnd]
        end = _text(row.get("period_end"), 40)
        section = {
            "round": rnd, "label": end or f"round {rnd}",
            "period_start": _text(row.get("period_start"), 40) or None, "period_end": end or None,
            "arbiter_status": "not_applicable", "arbiter_problems": [], "mechanical_only": False,
            "narrative": "", "moves": [], "held_position": [], "facts_changed": [], "events": [],
            "shocks_fired": [], "red_lines_crossed": [], "offers": [], "alliances": [], "behaviour": {},
            "refs": [{"file": "world_digest.jsonl", "round": rnd, "id": f"round:{rnd}"}],
        }
        if stub:
            section["stub"] = True
        else:
            digest = _text(row.get("digest"), 4000)
            if digest:
                section["events"].append({"kind": "digest", "text": digest, "actors": [], "ref": section["refs"][0]})
        periods.append(section)
    return periods


# ── deterministic synthesis ─────────────────────────────────────────────────────────────

def _max_delta_label(art: _Artifacts, periods: Sequence[Dict[str, Any]]) -> Optional[str]:
    best: Tuple[float, Optional[str]] = (-1.0, None)
    labels = {int(p["round"]): p["label"] for p in periods}
    for row in art.committed_history():
        delta = row.get("delta") if isinstance(row.get("delta"), dict) else {}
        total = sum(abs(float(v)) for v in delta.values() if _is_number(v))
        rnd = _as_int(row.get("round"))
        if rnd in labels and total > best[0]:
            best = (total, labels[rnd])
    return best[1]


def _join(items: Sequence[str], lang: str) -> str:
    L = _labels(lang)
    items = [i for i in items if i]
    if not items:
        return L["no_items"]
    sep = "；" if lang == "zh" else "; "
    return sep.join(items[:6])


def deterministic_synthesis(record: Dict[str, Any], art: Optional[_Artifacts] = None) -> Dict[str, Any]:
    """Templated overall prose built from the skeleton: numbers are only period labels, the
    final leading share and variable values that already sit in the record (G2)."""
    lang = record["language"]
    L = _labels(lang)
    periods = record["periods"]
    overall = record["overall"]
    if not periods:
        return {"generator": "deterministic", "text": "", "claims": []}
    first, last = periods[0], periods[-1]
    span = L["period_count_note"].format(n=len(periods), first=first["label"], last=last["label"])
    paragraphs: List[Tuple[str, List[Dict[str, Any]]]] = []
    shares = overall.get("shares") or {}
    final = shares.get("final") or {}
    if final:
        leader = shares.get("leader") or max(final, key=lambda k: (final[k], k))
        label = (_max_delta_label(art, periods) if art is not None else None) or last["label"]
        text = L["det_p1"].format(span=span, leader=leader, share=fmt_share(final.get(leader)), label=label)
        refs = [first["refs"][0], last["refs"][0], {"file": "world_state_trajectory.json", "round": int(last["round"]), "id": "outcome"}]
    else:
        text = L["det_p1_noshares"].format(span=span)
        refs = [first["refs"][0], last["refs"][0]]
    paragraphs.append((text, refs))
    red, accepted, breached, lapsed_offers, lapsed_commitments, refs2 = [], [], [], [], [], []
    for section in periods:
        for crossed in section.get("red_lines_crossed") or []:
            red.append(f"{crossed.get('actor') or ''}: {crossed.get('red_line') or ''} ({section['label']})".strip())
            refs2.append(section["refs"][0])
        for offer in section.get("offers") or []:
            text = f"{offer.get('from_actor')} → {offer.get('to_actor')} ({section['label']})"
            if offer.get("status") == "accepted":
                accepted.append(text)
                refs2.append(offer["ref"])
            elif offer.get("status") == "breached":
                breached.append(text)
                refs2.append(offer["ref"])
            elif offer.get("status") == "lapsed":
                lapsed_offers.append(text)
        for event in section.get("events") or []:
            if event.get("kind") == "commitment_lapsed":
                lapsed_commitments.append(f"{event.get('text')} ({section['label']})")
    paragraphs.append((L["det_p2_head"].format(red=_join(red, lang), accepted=_join(accepted, lang),
                                               breached=_join(breached, lang)),
                       _dedupe_refs(refs2) or [last["refs"][0]]))
    losers: List[str] = []
    if final:
        seed_shares = {}
        if art is not None:
            rows = art.trajectory.get("trajectory") if isinstance(art.trajectory.get("trajectory"), list) else []
            seed_row = next((r for r in rows if isinstance(r, dict) and _as_int(r.get("round")) == 0), None)
            if seed_row and isinstance(seed_row.get("shares"), dict):
                seed_shares = seed_row["shares"]
        for name, value in final.items():
            seed = seed_shares.get(name)
            if _is_number(seed) and _is_number(value) and value < seed:
                losers.append(str(name))
    paragraphs.append((L["det_p3_head"].format(losers=_join(losers, lang), lapsed=_join(lapsed_offers, lang),
                                               commitments=_join(lapsed_commitments, lang)),
                       [{"file": "world_state_trajectory.json", "round": int(last["round"]), "id": "outcome"}]
                       if final else [last["refs"][0]]))
    moved = []
    refs4 = []
    for tp in overall.get("turning_points") or []:
        if str(tp.get("why", "")).startswith(L["tp_variable"]):
            moved.append(str(tp["why"])[len(L["tp_variable"]) + 2:])
            refs4.append(tp["ref"])
    if moved:
        paragraphs.append((L["det_p4_head"].format(facts=_join(moved, lang)), _dedupe_refs(refs4)))
    return {"generator": "deterministic",
            "text": "\n\n".join(p for p, _ in paragraphs),
            "claims": [{"paragraph": i, "refs": refs} for i, (_, refs) in enumerate(paragraphs)]}


def _dedupe_refs(refs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for ref in refs:
        key = json.dumps(ref, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


# ── bounded LLM synthesis ───────────────────────────────────────────────────────────────

def _skeleton_for_prompt(record: Dict[str, Any]) -> str:
    """The deterministic skeleton the synthesis may draw on: nothing outside the record."""
    periods = []
    for p in record["periods"]:
        periods.append({
            "label": p["label"], "arbiter_status": p["arbiter_status"],
            "narrative": p.get("narrative") or "",
            "moves": [{"actor": m["actor"], "option": m["option"], "targets": m.get("targets"),
                       "public_statement": m.get("public_statement")} for m in p.get("moves") or []],
            "facts_changed": [{k: f.get(k) for k in ("variable", "from", "to", "unit", "cause")}
                              for f in p.get("facts_changed") or []],
            "events": [e.get("text") for e in p.get("events") or []],
            "offers": [{k: o.get(k) for k in ("from_actor", "to_actor", "status", "terms")} for o in p.get("offers") or []],
            "red_lines_crossed": _list(p.get("red_lines_crossed")),
            "shocks_fired": _list(p.get("shocks_fired")),
        })
    overall = record["overall"]
    skeleton = {
        "periods": periods,
        "final_variables": [v for v in overall.get("final_variables") or [] if v.get("changed")],
        "shares": overall.get("shares"),
        "turning_points": overall.get("turning_points"),
        "track_records": overall.get("track_records"),
    }
    return json.dumps(skeleton, ensure_ascii=False, indent=1)


def _synthesis_prompt(record: Dict[str, Any]) -> List[Dict[str, str]]:
    lang = record["language"]
    labels = ", ".join(p["label"] for p in record["periods"])
    if lang == "zh":
        system = ("你为一次多主体情景模拟撰写事后综述。模拟输出是「模拟」记录类别：不是证据，不是概率。"
                  "只能使用骨架中出现的名称、日期与数字，不得引入任何新数字；不得使用引用标记（如 [S1]）；"
                  "不得使用「证据」「概率」等词，情景份额只能称为「份额」；除非逐字复制骨架中的公开声明，不得引用任何人。")
        user = (f"根据以下确定性骨架，用中文写 2–4 段、总计不超过 400 字的综述，依次说明：主导机制、转折点、"
                f"未发生的事。每段结尾用括号列出该段依据的时段标签（可用标签：{labels}），例如「（{record['periods'][0]['label']}）」。"
                f"只输出以空行分隔的段落。\n\n骨架：\n{_skeleton_for_prompt(record)}")
    else:
        system = ("You write the after-action synthesis of a multi-agent scenario simulation. Simulation output is a "
                  "'simulated' record class: not evidence and not a probability. Use only names, dates and numbers that "
                  "appear in the skeleton and introduce no new number; no citation markers such as [S1]; do not use the "
                  "words 'evidence' or 'probability'; call scenario shares 'shares'; quote nobody unless the quote is "
                  "copied verbatim from a public_statement in the skeleton.")
        user = (f"From the deterministic skeleton below write 2 to 4 paragraphs, at most 220 words in total, covering in "
                f"order: dominant mechanisms, turning points, what did not happen. End every paragraph with the period "
                f"labels it draws on in parentheses (available labels: {labels}), for example "
                f"\"({record['periods'][0]['label']})\". Output only the paragraphs separated by blank lines.\n\n"
                f"Skeleton:\n{_skeleton_for_prompt(record)}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_synthesis(text: str, record: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", str(text or "").strip()) if p.strip()]
    if not paragraphs:
        return None, "empty synthesis"
    if len(paragraphs) > _SYNTHESIS_MAX_PARAGRAPHS:
        return None, f"too many paragraphs ({len(paragraphs)})"
    by_label = {p["label"]: p for p in record["periods"]}
    claims = []
    for i, paragraph in enumerate(paragraphs):
        refs = [by_label[label]["refs"][0] for label in sorted(by_label) if label in paragraph]
        if not refs:
            return None, f"paragraph {i + 1} names no period label"
        claims.append({"paragraph": i, "refs": refs})
    return {"generator": "llm", "text": "\n\n".join(paragraphs), "claims": claims}, ""


def _default_llm() -> Any:
    """The backend LLMClient, constructed as the world arbiter's caller constructs it."""
    from ..utils.llm_client import LLMClient
    return LLMClient()


def _apply_synthesis(record: Dict[str, Any], sim_dir: str, llm: Any) -> None:
    """One bounded call; the synthesis is kept only when it adds no gate hard issue."""
    from .simulation_record_gate import audit_record
    skeleton_issues = audit_record(sim_dir, record, write=False).get("hard_issues") or []
    if skeleton_issues:
        record["limits"]["synthesis_dropped"] = "gate: deterministic skeleton failed audit"
        return
    try:
        client = llm if llm is not None else _default_llm()
        raw = client.chat(messages=_synthesis_prompt(record), temperature=0.2, max_tokens=_SYNTHESIS_MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 — provider failure keeps the skeleton
        logger.warning("simulation record: synthesis call failed, deterministic skeleton kept: %s", exc)
        record["limits"]["synthesis_dropped"] = f"llm error: {type(exc).__name__}: {_text(exc, 160)}"
        return
    synthesis, reason = _parse_synthesis(raw, record)
    if synthesis is None:
        record["limits"]["synthesis_dropped"] = reason
        return
    candidate = json.loads(json.dumps(record, ensure_ascii=False))
    candidate["overall"]["synthesis"] = synthesis
    candidate["limits"]["synthesis_dropped"] = None
    new_issues = audit_record(sim_dir, candidate, write=False).get("hard_issues") or []
    if new_issues:
        record["limits"]["synthesis_dropped"] = f"gate: {new_issues[0]}"
        return
    record["overall"]["synthesis"] = synthesis
    record["limits"]["synthesis_dropped"] = None


# ── record assembly ─────────────────────────────────────────────────────────────────────

def build_record(sim_dir: str, *, language: Optional[str] = None, engine_hint: Optional[str] = None,
                 llm: Any = None, synthesis: Optional[bool] = None) -> Dict[str, Any]:
    """Compile the record for ``sim_dir``.  ``language`` is the run's output language (any
    spelling; resolved to ``en`` / ``zh``); ``engine_hint`` the pipeline's engine pin;
    ``llm`` an injected client (tests) — ``None`` constructs the backend client only when a
    synthesis call is actually made; ``synthesis`` overrides ``Config.SIM_RECORD_SYNTHESIS``."""
    art = _Artifacts(sim_dir)
    engine = resolve_engine(art, engine_hint)
    if engine == "world-v1":
        art.load_world_v1()
    lang = resolve_language(art, language)
    L = _labels(lang)

    health = _text(art.run_summary.get("simulation_health"), 40) or "unknown"
    if engine == "world-v1":
        validity = rc.world_result_validity(art.world_result)
        # The native world-v1 producer has no OASIS run_summary.json.
        if not art.run_summary:
            health = "ok" if validity == "valid" else "truncated"
    else:
        validity = decision_channel_validity(art.trajectory)
    if art.errors:
        validity = "invalid"
    stub = health not in ("ok", "llm_degraded") or validity != "valid"
    degraded = health == "llm_degraded"

    if engine == "oasis-reflexive":
        periods = _periods_reflexive(art, lang, stub=stub)
        setup = _setup_reflexive(art, lang)
    elif engine == "world-v1":
        periods = _world_v1_periods(art, lang, stub=stub)
        names = _world_v1_actor_names(art)
        setup = {"cast": [{"actor": n, "agency_class": "", "aliases": [], "red_lines": [], "documented_plans": []}
                          for n in sorted(names.values())],
                 "variables": [], "scenarios": [], "shocks": [], "seed_gaps": []}
    else:
        periods = _periods_thin(art, stub=stub)
        setup = _setup_reflexive(art, lang)
        setup["cast"] = setup["cast"] or [
            {"actor": _text(a.get("agent_name"), 160), "agency_class": "", "aliases": [], "red_lines": [],
             "documented_plans": []} for a in _list(art.run_summary.get("top_agents")) if isinstance(a, dict)]

    committed = len(periods)
    summary_committed = _as_int(art.world_summary.get("rounds_committed"))
    notes: List[str] = []
    if summary_committed is not None and summary_committed != committed and engine == "oasis-reflexive":
        notes.append(L["rounds_mismatch"].format(a=summary_committed, b=committed))
    if engine in ("oasis-inband", "oasis-hours"):
        notes.append(L["no_world_model"].format(engine=engine))
    if engine == "world-v1":
        notes.append(L["world_v1_no_narrative"])

    # the world summary's count, or the per-round history when it records more failures
    counted_failed = sum(1 for p in periods if p.get("arbiter_status") in ("failed", "invalid"))
    arbiter_failed = max(_as_int(art.world_summary.get("arbiter_failed_rounds")) or 0, counted_failed)
    seed_gaps = setup.get("seed_gaps") or []
    organic = _as_int(art.run_summary.get("organic_action_count"))

    if stub:
        overall: Dict[str, Any] = {"final_variables": [], "shares": {}, "turning_points": [], "track_records": []}
    elif engine == "oasis-reflexive":
        overall = {"final_variables": _final_variables(art), "shares": _shares_block(art, setup["scenarios"]),
                   "turning_points": _turning_points(periods, lang), "track_records": _track_records(art)}
    elif engine == "world-v1":
        overall = _world_v1_overall(art, periods, lang)
    else:
        overall = {"final_variables": [], "shares": _shares_block(art, setup["scenarios"]),
                   "turning_points": [], "track_records": []}

    planned = (_as_int(art.temporal.get("n_rounds")) or _as_int(art.run_summary.get("total_rounds"))
               or _as_int(art.trajectory.get("n_rounds")) or _as_int(art.world_result.get("totalRounds")) or committed)
    config_hash = (_text(art.config_manifest.get("simulation_config_sha256"), 80)
                   or next((_text(r.get("config_hash"), 80) for r in art.history if r.get("config_hash")), "") or None)
    simulation_id = (_text(art.run_summary.get("simulation_id") or art.world_state.get("simulation_id")
                           or art.state.get("simulation_id") or art.world_result.get("simulationId"), 80)
                     or os.path.basename(art.dir))
    entities = _dedupe(
        [c["actor"] for c in setup["cast"]] + [a for c in setup["cast"] for a in _list(c.get("aliases"))]
        + [v["name"] for v in setup["variables"]] + [v["name"] for v in overall.get("final_variables") or []]
        + list(setup["scenarios"]) + [p["label"] for p in periods] + _actor_names(art)[0] + _actor_names(art)[1])

    record: Dict[str, Any] = {
        "schema": rc.SCHEMA,
        "record_class": rc.RECORD_CLASS,
        "epistemic_status": rc.EPISTEMIC_STATUS,
        "simulation_id": simulation_id,
        "pipeline_id": _text(art.state.get("pipeline_id"), 80) or None,
        "config_hash": config_hash,
        "engine": engine,
        "language": lang,
        "as_of": (_text(art.temporal.get("as_of_date") or art.world.get("as_of_date") or art.config_as_of
                        or art.world_result.get("asOf"), 40)[:10] or None),
        "horizon_date": (_text(art.temporal.get("horizon_date") or art.world.get("horizon_date")
                               or art.trajectory.get("horizon_date") or art.world_result.get("horizon"), 40)[:10] or None),
        "calendar_unit": _text(art.temporal.get("unit") or art.trajectory.get("calendar_unit"), 20) or None,
        "rounds_planned": planned,
        "rounds_committed": committed,
        "health": {"simulation_health": health, "validity": validity, "arbiter_failed_rounds": arbiter_failed,
                   "seed_gaps": len(seed_gaps), "organic_actions": organic},
        "banner": rc.banner_for(lang),
        "setup": setup,
        "periods": periods,
        "overall": {**overall, "synthesis": {"generator": "deterministic", "text": "", "claims": []}},
        "limits": {"arbiter_failed_rounds": arbiter_failed, "seed_gaps": list(seed_gaps),
                   "behaviour_note": L["behaviour_note"], "synthesis_dropped": None, "notes": notes,
                   "stub": stub, "mechanical_only_rounds": [p["round"] for p in periods if p.get("mechanical_only")]},
        "entities_declared": sorted(entities),
        "generated_at": _utcnow(),
        "generator_version": GENERATOR_VERSION,
    }

    if stub:
        record["overall"]["synthesis"] = {
            "generator": "deterministic",
            "text": L["stub_sentence"].format(health=health, validity=validity),
            "claims": [{"paragraph": 0, "refs": [p["refs"][0] for p in periods[:1]] or
                        ([{"file": "world_result.json", "round": 0, "id": "round:0"}] if engine == "world-v1"
                         else [{"file": "run_summary.json", "round": 0, "id": "health"}])}],
        }
        record["limits"]["synthesis_dropped"] = f"health stub ({health}; validity {validity})"
        return record

    record["overall"]["synthesis"] = deterministic_synthesis(record, art)
    want_synthesis = bool(getattr(Config, "SIM_RECORD_SYNTHESIS", True)) if synthesis is None else bool(synthesis)
    if not want_synthesis:
        record["limits"]["synthesis_dropped"] = "disabled by SIM_RECORD_SYNTHESIS"
    elif degraded:
        record["limits"]["synthesis_dropped"] = "llm_degraded run: deterministic skeleton only"
    elif engine != "oasis-reflexive":
        record["limits"]["synthesis_dropped"] = f"engine {engine} has no arbiter narrative to synthesise"
    elif not periods:
        record["limits"]["synthesis_dropped"] = "no committed periods"
    else:
        _apply_synthesis(record, art.dir, llm)
    return record


# ── Markdown rendering (deterministic from the JSON) ────────────────────────────────────

def _md_escape(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _quote(text: str, lang: str) -> str:
    return f"「{text}」" if lang == "zh" else f"“{text}”"


def health_line(record: Dict[str, Any], lang: str) -> str:
    L = _labels(lang)
    health = record.get("health") or {}
    parts = [f"{L['health']}: {health.get('simulation_health')}", f"{L['validity']}: {health.get('validity')}",
             f"{L['arbiter_failed']}: {fmt_number(health.get('arbiter_failed_rounds'), lang)}",
             f"{L['seed_gaps']}: {fmt_number(health.get('seed_gaps'), lang)}"]
    if health.get("organic_actions") is not None:
        parts.append(f"{L['organic']}: {fmt_number(health.get('organic_actions'), lang)}")
    return " · ".join(parts)


def render_markdown(record: Dict[str, Any], lang: Optional[str] = None) -> str:
    """Deterministic Markdown for ``lang`` (``en`` / ``zh``; default the record's language).
    Only the labels follow ``lang``: verbatim artifact text (narratives, statements, terms)
    and the record's own authored prose (synthesis, turning points) stay in the record's
    language — a rendering, never a translation."""
    lang = "zh" if str(lang or record.get("language") or "en").lower().startswith("zh") else "en"
    L = _labels(lang)
    out: List[str] = [f"# {L['title']}", "", f"> {rc.banner_for(lang)}", "", f"_{L['subtitle']}_", ""]
    out.append(f"- {L['engine']}: `{record.get('engine')}` · {L['simulation']}: `{record.get('simulation_id')}`")
    out.append(f"- {L['as_of']}: {record.get('as_of') or '—'} · {L['horizon']}: {record.get('horizon_date') or '—'}"
               + (f" ({L['calendar_unit']}: {record.get('calendar_unit')})" if record.get("calendar_unit") else ""))
    out.append(f"- {L['periods']}: {record.get('rounds_committed')} / {record.get('rounds_planned')}")
    out.append(f"- {health_line(record, lang)}")
    limits = record.get("limits") or {}
    for note in limits.get("notes") or []:
        out.append(f"- {note}")
    out.append("")
    # setup
    setup = record.get("setup") or {}
    out.append(f"## {L['setup']}")
    out.append("")
    if setup.get("cast"):
        out.append(f"### {L['cast']}")
        for actor in setup["cast"]:
            bits = [f"**{_md_escape(actor.get('actor'))}**"]
            if actor.get("agency_class"):
                bits.append(f"({L['agency_class']}: {_md_escape(actor['agency_class'])})")
            if actor.get("aliases"):
                bits.append(f"{L['aliases']}: {', '.join(_md_escape(a) for a in actor['aliases'])}")
            if actor.get("red_lines"):
                bits.append(f"{L['red_lines']}: {'; '.join(_md_escape(r) for r in actor['red_lines'])}")
            if actor.get("documented_plans"):
                bits.append(f"{L['documented_plans']}: {'; '.join(_md_escape(p) for p in actor['documented_plans'])}")
            out.append("- " + " · ".join(bits))
        out.append("")
    if setup.get("variables"):
        out.append(f"### {L['variables']}")
        out.append(f"| {L['variable']} | {L['seed_value']} | {L['unit']} |")
        out.append("|---|---|---|")
        for var in setup["variables"]:
            out.append(f"| {_md_escape(var.get('name'))} | {fmt_number(var.get('seed_value'), lang)} | {_md_escape(var.get('unit'))} |")
        out.append("")
    if setup.get("scenarios"):
        out.append(f"### {L['scenarios']}")
        for name in setup["scenarios"]:
            out.append(f"- {_md_escape(name)}")
        out.append("")
    out.append(f"### {L['shocks']}")
    if setup.get("shocks"):
        for shock in setup["shocks"]:
            extra = " · ".join(x for x in (_md_escape(shock.get("base_rate")), _md_escape(shock.get("window"))) if x)
            out.append(f"- {_md_escape(shock.get('name'))}" + (f" ({extra})" if extra else ""))
    else:
        out.append(L["no_shocks"])
    out.append("")
    if setup.get("seed_gaps"):
        out.append(f"### {L['modelling_gaps']}")
        for gap in setup["seed_gaps"]:
            out.append(f"- {_md_escape(gap)}")
        out.append("")
    # periods
    for section in record.get("periods") or []:
        dates = ""
        if section.get("period_start") or section.get("period_end"):
            dates = f" ({section.get('period_start') or '—'} → {section.get('period_end') or '—'})"
        out.append(f"## {L['period']} {section.get('round')}: {_md_escape(section.get('label'))}{dates}")
        out.append("")
        status = f"{L['arbiter_status']}: {section.get('arbiter_status')}"
        if section.get("mechanical_only"):
            status += f" — {L['mechanical_only']}"
        out.append(status)
        if section.get("arbiter_problems"):
            out.append("")
            out.append(f"{L['arbiter_problems']}: " + "; ".join(_md_escape(p) for p in section["arbiter_problems"]))
        out.append("")
        if section.get("stub"):
            out.append(L["stub_period"])
            out.append("")
            continue
        if record.get("engine") == "oasis-reflexive":
            out.append(f"### {L['narrative']}")
            if section.get("narrative"):
                for line in str(section["narrative"]).splitlines():
                    out.append(f"> {line}" if line.strip() else ">")
            else:
                out.append(L["no_narrative"])
            out.append("")
        if section.get("moves"):
            out.append(f"### {L['moves']}")
            for move in section["moves"]:
                line = f"- **{_md_escape(move.get('actor'))}** — {_md_escape(move.get('option'))}"
                if move.get("targets"):
                    line += f" → {', '.join(_md_escape(t) for t in move['targets'])}"
                if move.get("public_statement"):
                    line += f"; {L['statement']}: {_quote(_md_escape(move['public_statement']), lang)}"
                commitment = move.get("commitment") or {}
                if commitment.get("text"):
                    line += f"; {L['commitment']}: {_md_escape(commitment['text'])}"
                    if commitment.get("due_periods") is not None:
                        line += f" ({L['due_periods']}: {commitment['due_periods']})"
                if move.get("terms"):
                    line += f"; {L['terms']}: {_md_escape(move['terms'])}"
                out.append(line)
            out.append("")
        if section.get("held_position"):
            out.append(f"### {L['held']}")
            out.append(", ".join(_md_escape(a) for a in section["held_position"]))
            out.append("")
        if section.get("facts_changed"):
            out.append(f"### {L['facts']}")
            out.append(f"| {L['variable']} | {L['from']} | {L['to']} | {L['unit']} | {L['cause']} |")
            out.append("|---|---|---|---|---|")
            for fact in section["facts_changed"]:
                out.append(f"| {_md_escape(fact.get('variable'))} | {fmt_number(fact.get('from'), lang)} | "
                           f"{fmt_number(fact.get('to'), lang)} | {_md_escape(fact.get('unit'))} | {_md_escape(fact.get('cause'))} |")
            out.append("")
        if section.get("events"):
            out.append(f"### {L['events']}")
            for event in section["events"]:
                kind = L.get(event.get("kind") or "", event.get("kind") or "")
                out.append(f"- [{_md_escape(kind)}] {_md_escape(event.get('text'))}")
            out.append("")
        if section.get("shocks_fired"):
            out.append(f"### {L['shocks_fired']}")
            for shock in section["shocks_fired"]:
                out.append(f"- {_md_escape(shock)}")
            out.append("")
        if section.get("offers"):
            out.append(f"### {L['offers']}")
            for offer in section["offers"]:
                status = L.get(offer.get("status") or "", offer.get("status") or "")
                line = (f"- {_md_escape(offer.get('from_actor'))} → {_md_escape(offer.get('to_actor'))} "
                        f"({_md_escape(offer.get('kind'))}, {L['status']}: {_md_escape(status)})")
                if offer.get("terms"):
                    line += f": {_md_escape(offer['terms'])}"
                out.append(line)
            out.append("")
        if section.get("red_lines_crossed"):
            out.append(f"### {L['red_lines_crossed']}")
            for crossed in section["red_lines_crossed"]:
                line = f"- {_md_escape(crossed.get('actor'))}: {_md_escape(crossed.get('red_line'))}"
                if crossed.get("by"):
                    line += f" ({L['by']} {_md_escape(crossed['by'])})"
                out.append(line)
            out.append("")
        if section.get("alliances"):
            out.append(f"### {L['alliances']}")
            for shift in section["alliances"]:
                if shift.get("kind") == "alliance_move":
                    out.append(f"- {_md_escape(shift.get('actor'))}: {_md_escape(shift.get('move'))} → {_md_escape(shift.get('target'))}")
                else:
                    out.append(f"- {_md_escape(shift.get('source'))} → {_md_escape(shift.get('target'))}: "
                               f"{_md_escape(shift.get('from'))} → {_md_escape(shift.get('to'))}")
            out.append("")
        behaviour = section.get("behaviour") or {}
        if behaviour:
            out.append(f"### {L['behaviour']}")
            out.append(", ".join(f"{k}={fmt_number(v, lang)}" for k, v in behaviour.items() if v is not None))
            out.append("")
            out.append(f"_{L['behaviour_note']}_")
            out.append("")
    # overall
    overall = record.get("overall") or {}
    out.append(f"## {L['overall']}")
    out.append("")
    final_vars = overall.get("final_variables") or []
    if final_vars:
        out.append(f"### {L['final_vs_seed']}")
        out.append(f"| {L['variable']} | {L['seed_value']} | {L['final_value']} | {L['unit']} |")
        out.append("|---|---|---|---|")
        changed = [v for v in final_vars if v.get("changed")]
        for var in changed:
            out.append(f"| {_md_escape(var.get('name'))} | {fmt_number(var.get('seed_value'), lang)} | "
                       f"{fmt_number(var.get('final_value'), lang)} | {_md_escape(var.get('unit'))} |")
        unchanged = len(final_vars) - len(changed)
        if unchanged:
            out.append("")
            out.append(f"{unchanged} {L['unchanged_variables']}")
        out.append("")
    shares = overall.get("shares") or {}
    out.append(f"### {L['shares']}")
    if shares.get("final"):
        out.append(f"_{L['shares_caption']}_")
        policy_note = share_policy_note(shares, lang)
        if policy_note:
            out.extend(["", policy_note])
        out.append("")
        paths = shares.get("paths") or {}
        per_scenario = paths.get("per_scenario") or {}
        if per_scenario:
            out.append(f"| {L['scenario']} | {L['final_share']} | {L['mean_share']} | p10 | p90 |")
            out.append("|---|---|---|---|---|")
        else:
            out.append(f"| {L['scenario']} | {L['final_share']} |")
            out.append("|---|---|")
        for name, value in sorted(shares["final"].items(), key=lambda kv: (-float(kv[1]), kv[0])):
            row = f"| {_md_escape(name)} | {fmt_share(value)} |"
            if per_scenario:
                stats = per_scenario.get(name) or {}
                row += f" {fmt_share(stats.get('mean'))} | {fmt_share(stats.get('p10'))} | {fmt_share(stats.get('p90'))} |"
            out.append(row)
        out.append("")
        tail = []
        if shares.get("leader"):
            tail.append(f"{L['leader']}: {_md_escape(shares['leader'])}")
        tail.append(f"{L['converged_at']}: {shares['converged_at']}" if shares.get("converged_at") is not None
                    else L["not_converged"])
        if paths.get("k"):
            tail.append(f"{paths['k']} {L['paths']}")
        out.append(" · ".join(tail))
    else:
        out.append(L["no_shares"])
    out.append("")
    out.append(f"### {L['turning_points']}")
    if overall.get("turning_points"):
        for tp in overall["turning_points"]:
            out.append(f"- {L['period']} {tp.get('round')}: {_md_escape(tp.get('why'))}")
    else:
        out.append(L["no_turning_points"])
    out.append("")
    out.append(f"### {L['track_records']}")
    resolved = [t for t in overall.get("track_records") or [] if t.get("resolved")]
    if resolved:
        out.append(f"| {L['cast']} | {L['kept']} | {L['lapsed']} | {L['broken']} | {L['released']} | {L['open']} |")
        out.append("|---|---|---|---|---|---|")
        for t in resolved:
            out.append(f"| {_md_escape(t.get('actor'))} | {t.get('kept', 0)} | {t.get('lapsed', 0)} | "
                       f"{t.get('broken', 0)} | {t.get('released', 0)} | {t.get('open', 0)} |")
    else:
        out.append(L["no_track_records"])
    out.append("")
    synthesis = overall.get("synthesis") or {}
    out.append(f"### {L['synthesis']} ({L['generator']}: {synthesis.get('generator')})")
    out.append("")
    if synthesis.get("text"):
        out.append(str(synthesis["text"]).strip())
    out.append("")
    out.append(f"## {L['limits']}")
    out.append(f"- {L['arbiter_failed']}: {fmt_number(limits.get('arbiter_failed_rounds'), lang)}")
    for gap in limits.get("seed_gaps") or []:
        out.append(f"- {L['seed_gaps']}: {_md_escape(gap)}")
    out.append(f"- {L['behaviour_note']}")
    if limits.get("synthesis_dropped"):
        out.append(f"- {L['synthesis_dropped']}: {_md_escape(limits['synthesis_dropped'])}")
    out.append("")
    out.append(f"> {rc.banner_for(lang)}")
    out.append("")
    return "\n".join(out)


# ── writing ─────────────────────────────────────────────────────────────────────────────

def record_json_bytes(record: Dict[str, Any]) -> bytes:
    """Canonical bytes of ``simulation_record.json`` — the gate's serialization, so the
    audit's SHA-256 is the SHA-256 of the file on disk."""
    return rc.record_bytes(record)


def _atomic_write(path: str, data: bytes) -> None:
    rc.atomic_write(path, data)


def write_record(sim_dir: str, record: Dict[str, Any]) -> Dict[str, str]:
    """Write ``simulation_record.json``, ``simulation_record.md`` (rendered in the record's
    language) and ``simulation_record.zh.md`` (always the Chinese rendering, so the API's
    ``lang=zh`` has one fixed file; identical to ``.md`` for a Chinese record).  Both
    renderings are deterministic functions of the JSON; no translation call is made."""
    paths = rc.record_paths(sim_dir)
    lang = "zh" if str(record.get("language") or "").startswith("zh") else "en"
    _atomic_write(paths["json"], record_json_bytes(record))
    _atomic_write(paths["md"], render_markdown(record, lang).encode("utf-8"))
    _atomic_write(paths["md_zh"], render_markdown(record, "zh").encode("utf-8"))
    return {"json": paths["json"], "md": paths["md"], "md_zh": paths["md_zh"]}
