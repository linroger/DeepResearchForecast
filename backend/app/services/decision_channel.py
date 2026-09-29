"""NEXTSTEPS P1-1 (integration): evolve the outcome WorldState from agent decisions.

The pure modeling core is ``services.worldstate.WorldState``. This module is the
orchestration that turns a finished simulation into a modeled-outcome trajectory: for
each round it elicits, in one batched structured LLM call, where each active agent
*committed* (toward which forecast scenario, with what magnitude/confidence), weights
those commitments by the agent's **outcome power** (resource/structural leverage on the
result, NOT voice), and steps the WorldState. The final ``outcome()`` is what a
forecaster reads INSTEAD of voice-share ``final_stance_share``.

Run **post-simulation** (after both platforms finish) so there is a single shared
WorldState and zero coupling to the concurrent per-platform round loops — gated behind
``SIM_DECISION_CHANNEL`` (default OFF). The orchestration is pure given (actions, llm),
so it is unit-testable offline with a fake LLM (the per-round elicitation is the only
LLM touch).

Round elicitation is a **pure function of the frozen action log** (it sees the round
roster + the immutable *base* distribution, never the evolving shares), which makes it
safe to fan the rounds out in parallel under a bounded thread pool (SIM-6 / R2-EXEC-8)
and to de-duplicate identical rosters via a cache (R2-EXEC-10). The WorldState is then
``step``-ed strictly in round order during a cheap, serial replay.

Findings landed here: R2-SIM-1 (inject round posts + base WorldState shares + affect),
R2-SIM-2 (power-weighted commitments + influence kept for activation), R2-SIM-3 (feed
gains_if/loses_if incentives), SIM-5 (power-sort + DECISION_CHANNEL_MAX_ACTIVE cap),
SIM-6 / R2-EXEC-8 (parallel two-phase elicit→replay), R2-EXEC-10 (collapse the audience
tail into one weighted public block + per-roster cache), R2-SIM-12 (calendar-scaled
inertia), SIM-1 (windowed convergence early-stop signal), abstention (R2-CAL-13/SIM-9).

日历改造（temporal spec §4/§5/§6）：单轮核心抽为 ``elicit_round(roster, period_ctx)``，
供轮内（in-band，run_parallel_simulation 日历回路）与本模块 post-hoc 回放共用；
``run_decision_channel(round_dates=...)`` 提供精确 round→时段映射时，提示词切换为
"时段"框架（基线锚定保留、演化份额继续隐藏）、缓存键为 (roster 签名, 时段 label)、
decisions/轨迹行带 period_end，输出 schema v3。``round_dates=None`` → 旧路径逐字节不变。
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .decision_validation import summarize_validation, validate_round_decisions
from .worldstate import (
    CONVERGENCE_POLICY_V1,
    ROUND_STATUS_ABSTAINED,
    ROUND_STATUS_COMMITTED,
    ROUND_STATUS_FAILED,
    ROUND_STATUS_MISSING,
    ROUND_STATUS_SILENT,
    WorldState,
    commitments_from_decisions,
)

# 仅用 stdlib logging，保持本模块导入纯净（子进程 in-band 演化直接 import 本模块）。
logger = logging.getLogger(__name__)

# Synthetic roster id for the collapsed audience tail (R2-EXEC-10). A string id never
# collides with the integer agent ids OASIS emits.
PUBLIC_BLOCK_ID = "__public__"
# Literal an agent may emit to opt out of committing this round (R2-CAL-13/SIM-9). It is
# intentionally NOT in the candidate scenario set, so it is filtered to a no-op weight.
ABSTAIN_TOKEN = "弃权"

# 日历时段单位 → 中文（spec §5 verbatim 映射）。
_UNIT_ZH = {"day": "天", "week": "周", "half_month": "半月", "month": "月",
            "quarter": "季度", "half_year": "半年"}
# 单位名义天数（与 sim_timeline 的 NOMINAL 一致），用于从时段长度反推单位、
# 以及日历模式下 _inertia_for_gap 的 avg_gap（= 单位名义天数）。
_UNIT_NOMINAL_DAYS = [("day", 1.0), ("week", 7.0), ("half_month", 15.22),
                      ("month", 30.44), ("quarter", 91.31), ("half_year", 182.62)]


def _cfg(name: str, default: Any) -> Any:
    """Read a Config flag degrade-safely (config.py is owned by another bucket)."""
    try:
        from ..config import Config  # local import keeps this module import-light/testable
        return getattr(Config, name, default)
    except Exception:  # noqa: BLE001 — never let config wiring break the channel
        return default


def _render_incentives(meta: Dict[str, Any]) -> str:
    """R2-SIM-3: compact gains_if/loses_if hint so commitments follow incentives."""
    gains = str(meta.get("gains_if") or "").strip()
    loses = str(meta.get("loses_if") or "").strip()
    bits = []
    if gains:
        bits.append(f"利好于：{gains}")
    if loses:
        bits.append(f"受损于：{loses}")
    return ("；".join(bits)) if bits else ""


def _render_roster_line(a: Dict[str, Any]) -> str:
    """One roster line, optionally enriched with this round's posts + affect (R2-SIM-1)
    and the agent's incentives (R2-SIM-3). All extras are best-effort: absent → omitted,
    so the line degrades to the original ``id/name/stance/influence`` form."""
    base = (f"- id={a.get('agent_id')} {a.get('name', '')}（立场：{a.get('stance', '?')}，"
            f"影响力：{a.get('influence', '?')}）")
    extras: List[str] = []
    inc = _render_incentives(a)
    if inc:
        extras.append(inc)
    affect = str(a.get("affect") or "").strip()
    if affect:
        extras.append(f"当前状态：{affect}")
    post = str(a.get("post") or "").strip()
    if post:
        snippet = post.replace("\n", " ")[:120]
        extras.append(f"本轮发声：{snippet}")
    if extras:
        base += "｜" + "；".join(extras)
    return base


def _period_days(period: Optional[Dict[str, Any]]) -> Optional[int]:
    """一个时段覆盖的日历天数（含首尾）；日期缺失/不可解析 → None。"""
    if not isinstance(period, dict):
        return None
    ps = _parse_date(period.get("period_start"))
    pe = _parse_date(period.get("period_end"))
    if ps is None or pe is None:
        return None
    d = (pe - ps).days + 1
    return d if d > 0 else None


def _unit_for_days(days: float) -> str:
    """按名义天数取最近的日历单位（day/…/half_year）。"""
    return min(_UNIT_NOMINAL_DAYS, key=lambda kv: abs(kv[1] - float(days)))[0]


def _infer_calendar_unit(round_dates: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """从 round_dates 的时段长度中位数反推日历单位（RoundPeriod 不携带 unit；
    snap 产生的首/尾残段用中位数天然滤掉）。全部不可解析 → None。"""
    lens = sorted(d for d in (_period_days(p) for p in (round_dates or [])
                              if isinstance(p, dict)) if d)
    if not lens:
        return None
    return _unit_for_days(lens[len(lens) // 2])


def _render_period_block(round_num: int, n_rounds: Optional[int],
                         period: Optional[Dict[str, Any]],
                         horizon_date: Optional[str],
                         unit: Optional[str]) -> str:
    """spec §5 的时段框架（verbatim 模板）。period 缺失/不完整 → ""（走旧的轮次框架）。"""
    if not isinstance(period, dict):
        return ""
    ps, pe = period.get("period_start"), period.get("period_end")
    if not ps or not pe:
        return ""
    u = str(unit or period.get("unit") or "")
    if not u:
        d = _period_days(period)
        u = _unit_for_days(d) if d else ""
    unit_zh = _UNIT_ZH.get(u, u) or "时段"
    total = ""
    try:
        if n_rounds:
            total = f"/{int(n_rounds)}"
    except (TypeError, ValueError):
        total = ""
    block = f"时段：第 {round_num}{total} 轮，覆盖 {ps} 至 {pe}（一个{unit_zh}）。\n"
    hd, ped = _parse_date(horizon_date), _parse_date(str(pe))
    if hd is not None and ped is not None:
        block += f"距离判定日 {horizon_date} 还有 {(hd - ped).days} 天。\n"
    block += "请给出你的行动体在这一整个时段内的实际投入方向与行动承诺。\n"
    return block


def _build_round_decision_prompt(scenarios: List[str], active: List[Dict[str, Any]],
                                 round_num: int, as_of: Optional[str],
                                 base_shares: Optional[Dict[str, float]] = None,
                                 abstain_allowed: bool = True,
                                 period: Optional[Dict[str, Any]] = None,
                                 n_rounds: Optional[int] = None,
                                 horizon_date: Optional[str] = None,
                                 unit: Optional[str] = None) -> str:
    sc_list = "、".join(scenarios)
    roster = "\n".join(_render_roster_line(a) for a in active)
    when = f"（对应时点约 {as_of}）" if as_of else ""
    # 日历模式（spec §5）：用"时段"框架替换"第 N 轮（对应时点约 …）"；
    # 基线锚定与"只喂种子先验、绝不喂演化份额"的守卫在两种模式下原样保留。
    period_block = _render_period_block(round_num, n_rounds, period, horizon_date, unit)
    lead = period_block if period_block else f"第 {round_num} 轮{when}的"
    # R2-SIM-1: anchor on the modeled base distribution (the seeded prior). It is the
    # immutable reference for every round (NOT the evolving per-round shares), which is
    # what keeps elicitation a pure, parallel-safe function of the frozen log.
    base_line = ""
    if base_shares:
        try:
            ordered = sorted(base_shares.items(), key=lambda kv: -float(kv[1]))
            base_line = ("当前建模基线分布（外部视角，仅供参考，不要机械照抄）："
                         + "，".join(f"{k}={float(v):.0%}" for k, v in ordered) + "。\n")
        except Exception:  # noqa: BLE001
            base_line = ""
    abstain_line = (
        f'若某角色本轮在结果上没有实质利害或无法判断，可让它选择 "{ABSTAIN_TOKEN}"（不计入）。\n'
        if abstain_allowed else "")
    return (
        f"这是一个预测推演。候选**互斥**情景：{sc_list}。\n"
        f"{base_line}"
        f"{lead}活跃角色会基于其立场/利益，对**结果**做出本轮的实质承诺"
        "（投票/下单/站队/分配，而非单纯发言）。为每个角色判断它本轮最倾向促成**哪一个**情景，"
        "以及力度 magnitude(0-1) 与信心 confidence(0-1)。\n"
        f"{abstain_line}"
        "只输出 JSON（不要解释）："
        '{"decisions": [{"agent_id": <id>, "scenario": "<必须取自上面候选>", '
        '"magnitude": 0-1, "confidence": 0-1}]}\n'
        f"角色名册：\n{roster}\n"
    )


def _elicit_round_decisions(llm, scenarios: List[str], active: List[Dict[str, Any]],
                            round_num: int, as_of: Optional[str] = None,
                            base_shares: Optional[Dict[str, float]] = None,
                            abstain_allowed: bool = True,
                            period: Optional[Dict[str, Any]] = None,
                            n_rounds: Optional[int] = None,
                            horizon_date: Optional[str] = None,
                            unit: Optional[str] = None,
                            report: Optional[Dict[str, Any]] = None,
                            ) -> Tuple[List[Dict[str, Any]], str]:
    """One batched structured call assigning each active agent a scenario commitment.

    Returns ``(decisions, round_status)`` where ``decisions`` is
    ``[{agent_id, scenario, magnitude, confidence}]`` (scenario validated against
    the candidate set; ``ABSTAIN_TOKEN`` and any other non-candidate value are
    dropped) and ``round_status`` is the Foglamp WP1 (1C/I-16) typed outcome:

    - ``committed``  — at least one validated commitment
    - ``abstained``  — the model answered and every agent explicitly abstained
    - ``silent``     — the model answered but produced no usable decision
    - ``failed``     — provider/transport/contract failure (exception or
      malformed payload). NOT interchangeable with abstention or equilibrium.
    - ``missing``    — elicitation was not attempted (empty roster/scenarios)

    Degrade-safe: empty inputs or any failure still yield an empty decision
    list; the caller decides what the status means for WorldState/convergence.
    ``period``/``n_rounds``/``horizon_date``/``unit`` 仅在日历模式提供，切换提示词
    为 spec §5 的时段框架。

    SIM-2 (C26): with ``DECISION_CHANNEL_VALIDATION`` on (default) the reply is
    bound to ``active`` by ``validate_round_decisions`` (canonical roster ids,
    unknown ids and duplicates dropped, magnitude/confidence finite and clamped
    to [0, 1]) and its reason-coded record is copied into ``report``; a failed
    call or payload sets ``report["measured"] = False``. ``max_tokens`` scales
    with rosters above 17 entries. With the flag off the legacy loop runs
    unchanged and ``report`` is untouched.
    """
    if not active or not scenarios:
        return [], ROUND_STATUS_MISSING
    validate = bool(_cfg("DECISION_CHANNEL_VALIDATION", True))
    # SIM-2: ~96 output tokens per roster row plus headroom; 2048 up to 17 rows.
    max_tokens = min(8192, max(2048, 96 * (len(active) + 1) + 256)) if validate else 2048
    try:
        raw = llm.chat_json(
            messages=[{"role": "user",
                       "content": _build_round_decision_prompt(
                           scenarios, active, round_num, as_of, base_shares, abstain_allowed,
                           period=period, n_rounds=n_rounds,
                           horizon_date=horizon_date, unit=unit)}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
    except Exception as _elicit_err:  # noqa: BLE001 — 一轮 elicit 失败不拖垮整条决策通道
        # Foglamp WP1 (1C/I-16)：失败必须显式入账（round_status=failed），不得再
        # 伪装成「无承诺→先验静态演化→看似收敛」。升级为 warning 级告警。
        logger.warning("决策通道单轮 elicit 失败（round_status=failed，本轮不更新 WorldState）: %s",
                       _elicit_err)
        if validate and report is not None:
            report["measured"] = False
        return [], ROUND_STATUS_FAILED
    decs = raw.get("decisions") if isinstance(raw, dict) else None
    if not isinstance(decs, list):
        # 模型返回了不符合契约的载荷：这是失败，不是沉默（I-16）。
        if validate and report is not None:
            report["measured"] = False
        return [], ROUND_STATUS_FAILED
    if validate:
        try:
            checked = validate_round_decisions(decs, active, scenarios,
                                               abstain_token=ABSTAIN_TOKEN)
        except Exception as _val_err:  # noqa: BLE001 — fail closed: an unvalidated reply never votes
            logger.warning("决策通道单轮校验异常（round_status=failed，本轮不更新 WorldState）: %s",
                           _val_err)
            if report is not None:
                report["measured"] = False
            return [], ROUND_STATUS_FAILED
        if report is not None:
            report.update(checked["record"])
        return checked["accepted"], checked["round_status"]
    out: List[Dict[str, Any]] = []
    abstained = 0
    valid = set(scenarios)
    for d in decs:
        if not isinstance(d, dict):
            continue
        sc = str(d.get("scenario") or "").strip()
        if sc == ABSTAIN_TOKEN:
            abstained += 1  # explicit opt-out (R2-CAL-13/SIM-9) — valid evidence
            continue
        if sc not in valid:  # invalid/non-candidate → no commitment
            continue
        out.append({
            "agent_id": d.get("agent_id"),
            "scenario": sc,
            "magnitude": d.get("magnitude", 1.0),
            "confidence": d.get("confidence", 0.7),
        })
    if out:
        return out, ROUND_STATUS_COMMITTED
    return [], (ROUND_STATUS_ABSTAINED if abstained else ROUND_STATUS_SILENT)


def elicit_round(roster: List[Dict[str, Any]],
                 period_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """日历改造（spec §4）：单轮 elicitation 核心，in-band（run_parallel_simulation 的
    轮内世界演化）与 post-hoc（``run_decision_channel`` 回放）两条路径共用。

    ``roster``：``_build_active_roster`` 的输出。``period_ctx`` 键：
    ``llm``/``scenarios``（必需）；``base_shares``、``abstain_allowed``（默认 True）、
    ``round_num``（1 基）、``n_rounds``、``as_of``（hours 兼容）、``horizon_date``、
    ``unit``、``period``（``{period_start, period_end, label}``，日历模式）可选。

    返回可直接喂给 ``WorldState.step`` 的 commitments（``weight`` = outcome_power ×
    confidence，与 ``commitments_from_decisions`` 同口径），每项同时保留审计字段
    ``{agent_id, scenario, magnitude, confidence, round, outcome_power?, period_end?}``。
    Degrade-safe：空输入/任何失败 → ``[]``。

    Foglamp WP1 (1C/I-16)：本轮的类型化结果写入 ``period_ctx["round_status"]``
    （committed/abstained/silent/failed/missing）——调用方必须把它传给
    ``WorldState.step(round_status=...)``，使失败/沉默轮不再伪装成稳定。

    SIM-2 (C26): when ``DECISION_CHANNEL_VALIDATION`` produced a record it is
    written to ``period_ctx["decision_validation"]`` (``{"measured": False}``
    for a failed call); roster-canonical ids make the outcome-power lookup hit.
    """
    ctx = period_ctx or {}
    llm = ctx.get("llm")
    scenarios = [str(s) for s in (ctx.get("scenarios") or []) if str(s).strip()]
    if llm is None or not scenarios or not roster:
        if isinstance(period_ctx, dict):
            period_ctx["round_status"] = ROUND_STATUS_MISSING
        return []
    try:
        rnd = int(ctx.get("round_num") or 0)
    except (TypeError, ValueError):
        rnd = 0
    period = ctx.get("period") if isinstance(ctx.get("period"), dict) else None
    report: Dict[str, Any] = {}
    decisions, round_status = _elicit_round_decisions(
        llm, scenarios, roster, rnd, ctx.get("as_of"),
        ctx.get("base_shares"), bool(ctx.get("abstain_allowed", True)),
        period=period, n_rounds=ctx.get("n_rounds"),
        horizon_date=ctx.get("horizon_date"), unit=ctx.get("unit"), report=report)
    if isinstance(period_ctx, dict):
        period_ctx["round_status"] = round_status
        if report:  # SIM-2: per-round validation record (absent with the flag off)
            period_ctx["decision_validation"] = report
    pmap = {e.get("agent_id"): e.get("outcome_power", 1.0) for e in roster}
    period_end = str(period.get("period_end")) if period and period.get("period_end") else None
    out: List[Dict[str, Any]] = []
    for d in decisions:
        c = dict(d)
        c["round"] = rnd
        if c.get("agent_id") in pmap:  # R2-SIM-2: carry the actor's outcome power
            c["outcome_power"] = pmap[c["agent_id"]]
        if period_end:
            c["period_end"] = period_end  # spec §4/§6: decisions 行带 period_end
        conv = commitments_from_decisions([c])
        c["weight"] = conv[0]["weight"] if conv else 0.0
        out.append(c)
    return out


def _to_weight(v: Any, default: float = 1.0) -> float:
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return default


def _activation_weight_map(agent_configs: Optional[List[Dict[str, Any]]]) -> Dict[Any, float]:
    """{agent_id: influence_weight} — drives *activation*/roster ranking (who is loud
    enough to act), kept distinct from outcome power per R2-SIM-2."""
    out: Dict[Any, float] = {}
    for c in (agent_configs or []):
        if isinstance(c, dict) and c.get("agent_id") is not None:
            out[c["agent_id"]] = _to_weight(c.get("influence_weight", 1.0))
    return out


def _outcome_power_map(agent_configs: Optional[List[Dict[str, Any]]]) -> Dict[Any, float]:
    """{agent_id: outcome_power} — drives how much a commitment moves the OUTCOME.

    Foglamp WP1 (I-15): the map contains ONLY explicitly declared
    ``outcome_power`` values. Visibility (``influence_weight`` — the chance of
    being seen/heard) is never reused as institutional outcome power: a missing
    power is UNKNOWN, and downstream consumers substitute a declared-neutral
    1.0 (labeled ``outcome_power_known=False``), not the actor's loudness.
    The pre-containment fallback let media prominence become legal/political/
    resource power by construction (R2-SIM-2 preserved it "so today's behavior
    is preserved"); that default is removed.
    """
    out: Dict[Any, float] = {}
    for c in (agent_configs or []):
        if not isinstance(c, dict) or c.get("agent_id") is None:
            continue
        power = c.get("outcome_power")
        if power is None:
            continue  # unknown power stays unknown (I-15) — no visibility fallback
        out[c["agent_id"]] = _to_weight(power)
    return out


def _agent_meta_map(agent_configs: Optional[List[Dict[str, Any]]]) -> Dict[Any, Dict[str, Any]]:
    out: Dict[Any, Dict[str, Any]] = {}
    for c in (agent_configs or []):
        if isinstance(c, dict) and c.get("agent_id") is not None:
            out[c["agent_id"]] = {
                "agent_id": c.get("agent_id"),
                "name": c.get("entity_name") or c.get("name") or "",
                "stance": c.get("stance", ""),
                "influence": c.get("influence", c.get("influence_weight", "")),
                # R2-SIM-3: incentives drive which scenario a rational agent commits to.
                "gains_if": c.get("gains_if", ""),
                "loses_if": c.get("loses_if", ""),
            }
    return out


def _build_active_roster(entries: List[Dict[str, Any]],
                         activation: Dict[Any, float],
                         power: Dict[Any, float],
                         cap: int) -> List[Dict[str, Any]]:
    """SIM-5 + R2-EXEC-10: rank the round's actors by *activation* (influence) and keep
    the top ``cap`` individually; collapse the remaining tail into ONE weighted public
    block whose outcome power is the sum of the tail's (so the silent-majority signal is
    aggregated, never silently dropped by truncation).

    Foglamp WP1 (I-15): an actor without an explicitly declared ``outcome_power``
    receives a declared-neutral 1.0 with ``outcome_power_known=False`` — never
    its activation/visibility weight. Loudness must not become outcome power.
    """
    enriched = []
    for e in entries:
        aid = e.get("agent_id")
        ee = dict(e)
        ee["_act"] = activation.get(aid, _to_weight(e.get("influence"), 1.0))
        if aid in power:
            ee["outcome_power"] = power[aid]
            ee["outcome_power_known"] = True
        else:
            ee["outcome_power"] = 1.0  # declared-neutral default, NOT visibility (I-15)
            ee["outcome_power_known"] = False
        enriched.append(ee)
    enriched.sort(key=lambda x: -float(x.get("_act", 0.0)))
    if cap <= 0 or len(enriched) <= cap:
        head, tail = enriched, []
    else:
        head, tail = enriched[:cap], enriched[cap:]
    roster = [{k: v for k, v in e.items() if k != "_act"} for e in head]
    if tail:
        tail_power = sum(float(e.get("outcome_power", 0.0)) for e in tail)
        roster.append({
            "agent_id": PUBLIC_BLOCK_ID,
            "name": f"其他公众（{len(tail)} 名沉默多数的合并代表）",
            "stance": "mixed",
            "influence": round(tail_power, 4),
            "outcome_power": tail_power,
        })
    return roster


def _roster_signature(active: List[Dict[str, Any]]) -> Tuple:
    """Stable key for caching identical rosters across rounds (R2-EXEC-10). The decision
    depends only on who is in the roster and their stance/incentives — not the round
    number — so a stable roster reuses one elicitation."""
    return tuple(sorted(
        (str(a.get("agent_id")), str(a.get("stance", "")),
         str(a.get("gains_if", "")), str(a.get("loses_if", "")),
         str(a.get("post", "")))
        for a in active
    ))


def _safe_round_to_date(round_to_date, rnd: int) -> Optional[str]:
    if round_to_date is None:
        return None
    try:
        v = round_to_date(rnd)
        return str(v) if v else None
    except Exception:  # noqa: BLE001
        return None


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except (TypeError, ValueError):
        return None


def _inertia_for_gap(base: float, prev_s: Optional[str], cur_s: Optional[str],
                     avg_gap_days: float) -> Optional[float]:
    """R2-SIM-12: scale per-round inertia by the calendar gap. Persistence over one
    *average* step is ``base``; over a gap of ``g`` days it is ``base ** (g/avg)`` so a
    longer real-time gap lets more change through (lower inertia) and a shorter one holds
    more. Clamped to [0.3, 0.95]. Returns ``None`` (→ use ``base``) whenever dates are
    missing or ``base`` is degenerate, so the no-date path is unchanged.
    """
    if not (0.0 < base < 1.0) or avg_gap_days <= 0:
        return None
    pd, cd = _parse_date(prev_s), _parse_date(cur_s)
    if pd is None or cd is None:
        return None
    gap = (cd - pd).days
    if gap < 0:
        return None
    eff = base ** (gap / avg_gap_days)
    return max(0.3, min(0.95, eff))


def _avg_gap_days(seed: Dict[str, Any], as_of_by_round: Dict[int, Optional[str]]) -> float:
    """Average calendar days per round across the run, for R2-SIM-12 normalization."""
    dated = [(_parse_date(seed.get("as_of_date")), 0)]
    dated += [(_parse_date(v), r) for r, v in as_of_by_round.items()]
    pts = [(d, r) for d, r in dated if d is not None]
    if len(pts) < 2:
        return 0.0
    pts.sort(key=lambda x: x[1])
    span = (pts[-1][0] - pts[0][0]).days
    rounds = pts[-1][1] - pts[0][1]
    return (span / rounds) if (span > 0 and rounds > 0) else 0.0


def _fan_out_elicit(tasks: Dict[Any, Tuple[List[Dict[str, Any]], Dict[str, Any]]],
                    concurrency: int) -> Dict[Any, List[Dict[str, Any]]]:
    """SIM-6 / R2-EXEC-8: run one elicitation per *unique* roster key, in parallel under
    a bounded pool. ``tasks[key] = (roster, period_ctx)``; each task runs through
    ``elicit_round`` (the single per-round core shared with the in-band calendar path).
    Returns ``{key: commitments}``. Each task is independent (pure over the frozen log)
    so ordering does not matter; the WorldState is stepped later in round order. A
    failing task degrades to ``[]`` for that key only.
    """
    results: Dict[Any, List[Dict[str, Any]]] = {}
    if not tasks:
        return results

    def _run(key):
        active, ctx = tasks[key]
        return key, elicit_round(active, ctx)

    workers = max(1, min(int(concurrency or 1), len(tasks)))
    if workers == 1:
        for key in tasks:
            _, decs = _run(key)
            results[key] = decs
        return results
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="decision-elicit") as ex:
        for key, decs in ex.map(_run, list(tasks.keys())):
            results[key] = decs
    return results


_FALLBACK_MAX_SHARE_DEFAULT = 0.5


def _fallback_max_share() -> float:
    """SIM-2: ``DECISION_CHANNEL_FALLBACK_MAX_SHARE`` as a share in ``[0, 1]``.

    A non-numeric, non-finite or out-of-range value (``nan``, ``50`` meant as a
    percent, a negative) would silently disable or invert the fallback gate, so
    it falls back to the 0.5 default with a warning instead (fail closed).
    """
    raw = _cfg("DECISION_CHANNEL_FALLBACK_MAX_SHARE", _FALLBACK_MAX_SHARE_DEFAULT)
    try:
        threshold = float(raw)
    except (TypeError, ValueError):
        threshold = math.nan
    if math.isfinite(threshold) and 0.0 <= threshold <= 1.0:
        return threshold
    logger.warning("DECISION_CHANNEL_FALLBACK_MAX_SHARE=%r 不是 [0,1] 内的有限份额，"
                   "按默认 %.1f 裁定", raw, _FALLBACK_MAX_SHARE_DEFAULT)
    return _FALLBACK_MAX_SHARE_DEFAULT


def decision_channel_verdict(accounting: Dict[str, Any], *,
                             unaccounted_rounds: int = 0,
                             fallback_share: Optional[float] = None) -> Dict[str, Any]:
    """Foglamp WP1 (1C/1D, I-11/I-16) typed run-level validity verdict, shared by both
    decision-channel producers (SIM-1): post-hoc ``run_decision_channel`` and the
    in-band calendar evolution in run_parallel_simulation.

    ``accounting`` is ``WorldState.round_accounting()`` and is never mutated.
    ``unaccounted_rounds`` counts rounds the run executed but the WorldState never
    stepped (in-band: pre-resume rounds after a lossy resume, rounds dead on every
    platform). They are booked as ``missing`` and widen the coverage denominator —
    the frozen policy's rule "missing data yields inconclusive, not convergence".
    With ``0`` the returned accounting equals the input (no new key).

    The two producers share the verdict rule but not the round set they account:
    post-hoc ``run_decision_channel`` replays only rounds present in the action log
    and always passes ``0``, so a round without any action never reaches its
    denominator, whereas the in-band producer books every round it saw but never
    stepped. The same run can therefore be ``inconclusive`` in-band and ``valid``
    post-hoc.

      - valid        — no failed rounds and at least
                       ``CONVERGENCE_POLICY_V1["min_valid_coverage"]`` of the
                       accounted rounds (including unaccounted rounds booked as
                       missing) are committed/abstained
      - inconclusive — some usable rounds, but provider failures (``failed_rounds``)
                       or silent/missing rounds (``low_valid_coverage``) keep the run
                       below the frozen convergence policy's evidence bar
      - invalid      — zero usable rounds (``no_valid_rounds``; dead channel)

    SIM-2 (C26): ``fallback_share`` is the run-level share of roster slots
    without an accepted or abstained answer (``summarize_validation``). A run
    that would be ``valid`` becomes ``inconclusive`` (``fallback_share_exceeded``)
    when it exceeds ``DECISION_CHANNEL_FALLBACK_MAX_SHARE`` (validated by
    ``_fallback_max_share``) or is not finite; ``None`` (no validation record)
    leaves the verdict unchanged.

    A non-``valid`` run MUST NOT move a forecast: forecast_effect=no_update. Even a
    valid run defaults to diagnostic_only until an outcome-blind prospective study
    promotes a validated update rule (WP6/12/14); validated_update is never emitted
    (fail closed). ``CONVERGENCE_POLICY_V1`` is read, never modified.

    Returns ``{round_accounting, validity, validity_reasons, forecast_effect}``.
    """
    acct = dict(accounting)
    if isinstance(acct.get("counts"), dict):
        acct["counts"] = dict(acct["counts"])
    n = max(0, int(unaccounted_rounds))
    if n > 0:
        counts = acct["counts"] = dict(acct.get("counts") or {})
        counts[ROUND_STATUS_MISSING] = int(counts.get(ROUND_STATUS_MISSING, 0) or 0) + n
        acct["rounds_accounted"] = int(acct.get("rounds_accounted", 0) or 0) + n
        acct["missing_rounds"] = int(acct.get("missing_rounds", 0) or 0) + n
        acct["valid_coverage"] = round(
            int(acct.get("valid_transitions", 0) or 0) / acct["rounds_accounted"], 6)
        acct["unaccounted_rounds"] = n
    reasons: List[str] = []
    if int(acct.get("valid_transitions", 0) or 0) <= 0:
        validity = "invalid"
        reasons.append("no_valid_rounds")
    else:
        if int(acct.get("failed_rounds", 0) or 0) > 0:
            reasons.append("failed_rounds")
        if float(acct.get("valid_coverage", 0.0) or 0.0) < float(
                CONVERGENCE_POLICY_V1["min_valid_coverage"]):
            reasons.append("low_valid_coverage")
        validity = "inconclusive" if reasons else "valid"
    if validity == "valid" and fallback_share is not None:
        share = float(fallback_share)
        if not math.isfinite(share) or share > _fallback_max_share():
            validity = "inconclusive"
            reasons = ["fallback_share_exceeded"]
    if validity != "valid":
        forecast_effect = "no_update"
    else:
        effect_policy = str(_cfg("SIMULATION_FORECAST_EFFECT", "diagnostic_only")
                            or "diagnostic_only").strip().lower()
        # validated_update is unavailable until WP6/12/14 promotion (fail closed).
        forecast_effect = ("diagnostic_only" if effect_policy != "no_update"
                           else "no_update")
    return {
        "round_accounting": acct,
        "validity": validity,
        "validity_reasons": reasons,
        "forecast_effect": forecast_effect,
    }


def run_decision_channel(
    actions: List[Dict[str, Any]],
    agent_configs: Optional[List[Dict[str, Any]]],
    seed: Dict[str, Any],
    llm,
    *,
    inertia: float = 0.7,
    conv_eps: float = 0.02,
    round_to_date=None,
    round_dates: Optional[List[Dict[str, Any]]] = None,
    max_active_per_round: Optional[int] = None,
    concurrency: Optional[int] = None,
    abstain_allowed: bool = True,
    posts_by_round: Optional[Dict[int, Dict[Any, str]]] = None,
    affect_by_agent: Optional[Dict[Any, str]] = None,
) -> Dict[str, Any]:
    """Replay the simulation rounds → evolve a single WorldState → modeled outcome.

    ``actions``: list of ``{round, agent_id, agent_name}`` (the action log; each item may
    also carry ``post``/``text`` for R2-SIM-1). ``seed``: ``{scenarios, base_rates,
    as_of_date?, horizon_date?}`` (from ``actors.world_state_seed_from_actors``). ``llm``
    drives the per-round batched elicitation (``chat_json``). ``round_to_date`` maps a
    1-based round int → ISO date (P1-2). ``round_dates``（日历模式，spec §4）：
    ``temporal_config["round_dates"]`` 的精确映射（0 基 ``round`` →
    ``{period_start, period_end, label}``）——提供时提示词切换为时段框架、缓存键改为
    ``(roster 签名, 时段 label)``、decisions/轨迹行带 ``period_end``，并按
    ``WORLDSTATE_ENTROPY_MIX`` 传入每时段天数做熵地板；缺省 ``None`` 走旧路径，逐字节不变。
    ``max_active_per_round`` caps the individually listed actors per round (the
    tail collapses into one public block); ``None`` reads
    ``DECISION_CHANNEL_MAX_ACTIVE``. ``posts_by_round[round][agent_id]`` and
    ``affect_by_agent[agent_id]`` optionally enrich the prompt (R2-SIM-1). Returns
    ``{outcome, trajectory, decisions, converged_at, n_rounds, ...}``; empty seed → ``{}``.
    """
    scenarios = [str(s) for s in (seed or {}).get("scenarios", []) if str(s).strip()]
    if not scenarios:
        return {}
    seed = seed or {}
    ws = WorldState(scenarios, seed.get("base_rates"), inertia=inertia)
    base_shares = dict(ws.shares)  # immutable reference distribution for every round (R2-SIM-1)
    activation = _activation_weight_map(agent_configs)
    power = _outcome_power_map(agent_configs)
    meta = _agent_meta_map(agent_configs)
    posts_by_round = posts_by_round or {}
    affect_by_agent = affect_by_agent or {}

    # SIM-2: an explicit max_active_per_round wins; otherwise the DECISION_CHANNEL_MAX_ACTIVE
    # knob (default 60, the value this keyword used to default to).
    if max_active_per_round is not None:
        cap = int(max_active_per_round)
    else:
        cap = int(_cfg("DECISION_CHANNEL_MAX_ACTIVE", 60) or 60)
    if concurrency is None:
        concurrency = int(_cfg("OASIS_SEMAPHORE", 8) or 8)

    # Group the frozen action log into per-round rosters (one entry per distinct actor),
    # enriching each entry with its meta + this round's post + affect (R2-SIM-1).
    by_round: Dict[int, "Dict[Any, Dict[str, Any]]"] = {}
    for a in (actions or []):
        if not isinstance(a, dict):
            continue
        try:
            rnd = int(a.get("round", a.get("round_num", 0)) or 0)
        except (TypeError, ValueError):
            continue
        aid = a.get("agent_id")
        if aid is None or rnd < 1:
            continue
        roster = by_round.setdefault(rnd, {})
        if aid not in roster:
            base = meta.get(aid, {"agent_id": aid, "name": a.get("agent_name", ""),
                                  "stance": "", "influence": ""})
            entry = dict(base)
            post = (posts_by_round.get(rnd, {}) or {}).get(aid) or a.get("post") or a.get("text")
            if post:
                entry["post"] = str(post)
            if affect_by_agent.get(aid):
                entry["affect"] = str(affect_by_agent[aid])
            roster[aid] = entry

    ordered_rounds = sorted(by_round)
    rosters: Dict[int, List[Dict[str, Any]]] = {
        rnd: _build_active_roster(list(by_round[rnd].values()), activation, power, cap)
        for rnd in ordered_rounds
    }

    # 日历模式（spec §4）：round_dates 是精确的 round→时段映射（0 基 round，runtime 轮号
    # 1 基）。as_of = period_end（喂 _inertia_for_gap 的是 snap 后不等长时段的真实 gap）。
    period_by_round: Dict[int, Dict[str, Any]] = {}
    for p in (round_dates or []):
        if not isinstance(p, dict):
            continue
        try:
            period_by_round[int(p.get("round")) + 1] = p
        except (TypeError, ValueError):
            continue
    calendar_unit = _infer_calendar_unit(round_dates) if period_by_round else None
    n_rounds_total = len(period_by_round) or None
    as_of_by_round: Dict[int, Optional[str]] = {}
    for rnd in ordered_rounds:
        p = period_by_round.get(rnd)
        as_of_by_round[rnd] = (str(p.get("period_end")) if p and p.get("period_end")
                               else _safe_round_to_date(round_to_date, rnd))

    # Phase 1 (parallel): one elicitation per unique (roster, date) key (R2-EXEC-10 cache
    # + SIM-6/R2-EXEC-8 fan-out). round_num for the prompt is the first round using the
    # key. 日历模式缓存键 = (roster 签名, 时段 label)——机制同旧的 (签名, as_of)。
    tasks: Dict[Any, Tuple[List[Dict[str, Any]], Dict[str, Any]]] = {}
    round_key: Dict[int, Any] = {}
    for rnd in ordered_rounds:
        active = rosters[rnd]
        p = period_by_round.get(rnd)
        key = (_roster_signature(active),
               str(p.get("label")) if p and p.get("label") else as_of_by_round[rnd])
        round_key[rnd] = key
        if key not in tasks:
            ctx: Dict[str, Any] = {
                "llm": llm, "scenarios": scenarios, "base_shares": base_shares,
                "abstain_allowed": abstain_allowed, "round_num": rnd,
                "as_of": as_of_by_round[rnd],
            }
            if p:
                ctx.update({"period": p, "n_rounds": n_rounds_total,
                            "horizon_date": seed.get("horizon_date"),
                            "unit": calendar_unit})
            tasks[key] = (active, ctx)
    results = _fan_out_elicit(tasks, concurrency)

    # Phase 2 (serial replay, strict round order): step the single shared WorldState.
    # 日历模式下 avg_gap = 单位名义天数（spec §4）；snap 后的首/尾残段 gap 短/长于名义值，
    # _inertia_for_gap 据此放行更少/更多变化。hours 路径沿用逐轮日期均值。
    if calendar_unit:
        avg_gap = dict(_UNIT_NOMINAL_DAYS).get(calendar_unit, 0.0)
    else:
        avg_gap = _avg_gap_days(seed, as_of_by_round)
    entropy_mix_on = bool(period_by_round) and bool(_cfg("WORLDSTATE_ENTROPY_MIX", True))
    conv_window = max(1, int(_cfg("SIM_CONVERGENCE_WINDOW", 3) or 3))
    trajectory: List[Dict[str, Any]] = [{"round": 0, **ws.outcome()}]
    if period_by_round and seed.get("as_of_date"):
        trajectory[0]["as_of"] = str(seed.get("as_of_date"))  # spec §6: 第 0 行 as_of=as_of_date
    all_decisions: List[Dict[str, Any]] = []
    validation_records: List[Dict[str, Any]] = []  # SIM-2: one per replayed round
    converged_at: Optional[int] = None
    stable_streak = 0
    prev_date = seed.get("as_of_date")
    for rnd in ordered_rounds:
        active = rosters[rnd]
        pmap = {e.get("agent_id"): e.get("outcome_power", 1.0) for e in active}
        p = period_by_round.get(rnd)
        period_end = str(p.get("period_end")) if p and p.get("period_end") else None
        decisions = []
        for c in results.get(round_key[rnd], []):
            # 审计行不含 step 用的 weight（旧口径不变）；round/outcome_power/period_end
            # 按真实轮次重写（缓存命中的 commitments 带的是首个使用轮的值）。
            d = {k: v for k, v in c.items() if k != "weight"}
            d["round"] = rnd
            if d.get("agent_id") in pmap:  # R2-SIM-2: carry the actor's outcome power
                d["outcome_power"] = pmap[d["agent_id"]]
            if period_end:
                d["period_end"] = period_end  # spec §4: decisions.jsonl 行带 period_end
            else:
                d.pop("period_end", None)
            decisions.append(d)
        all_decisions.extend(decisions)
        as_of = as_of_by_round[rnd]
        eff_inertia = _inertia_for_gap(inertia, prev_date, as_of, avg_gap)  # R2-SIM-12
        entropy_days = _period_days(p) if (entropy_mix_on and p) else None  # 熵地板（spec §4）
        # Foglamp WP1 (1C/I-16): the typed elicitation status was written into the
        # shared task ctx by elicit_round; a cached roster key reuses one status.
        task_ctx = tasks[round_key[rnd]][1] or {}
        round_status = str(task_ctx.get("round_status") or ROUND_STATUS_MISSING)
        ws.step(commitments_from_decisions(decisions), inertia=eff_inertia,
                entropy_mix_days=entropy_days, round_status=round_status)
        snap = {"round": rnd, **ws.outcome()}
        snap["round_status"] = round_status  # Foglamp 1C/I-16: per-round validity
        if as_of:
            snap["as_of"] = as_of
        if p:  # spec §6: 轨迹行带时段字段
            for fk in ("period_start", "period_end", "label"):
                if p.get(fk):
                    snap[fk] = str(p[fk])
        # SIM-2: the round's validation record; a cached roster key contributes it
        # once per replayed round, like its round_status.
        rec = task_ctx.get("decision_validation")
        if isinstance(rec, dict):
            snap["decision_validation"] = rec
            validation_records.append(rec)
        trajectory.append(snap)
        # SIM-1: windowed convergence — require the EWMA delta to stay below eps for
        # SIM_CONVERGENCE_WINDOW consecutive rounds (after a 2-round warmup) before the
        # trajectory is declared settled. Recorded as a calibration signal regardless of
        # whether the caller chooses to early-stop the live sim on it.
        if ws.converged(conv_eps):
            stable_streak += 1
            if converged_at is None and stable_streak >= conv_window and rnd >= 2:
                converged_at = rnd
        else:
            stable_streak = 0
        if as_of:
            prev_date = as_of

    ws.converged_at = converged_at
    out = ws.outcome()
    out["converged_at"] = converged_at
    # Foglamp WP1 (1C/1D, I-11/I-16): typed run-level validity verdict. The rule is
    # shared with the in-band calendar producer (SIM-1), but this path accounts only
    # rounds present in the action log (unaccounted_rounds=0) — see
    # decision_channel_verdict.
    validation_summary: Optional[Dict[str, Any]] = None
    if validation_records:  # SIM-2: run-level fallback_share folded into the verdict
        validation_summary = summarize_validation(
            validation_records,
            unmeasured_rounds=len(ordered_rounds) - len(validation_records))
    verdict = decision_channel_verdict(
        ws.round_accounting(),
        fallback_share=(validation_summary or {}).get("fallback_share"))
    result = {
        "outcome": out,
        "trajectory": trajectory,
        "decisions": all_decisions,
        "converged_at": converged_at,
        "n_rounds": max(ordered_rounds, default=0),
        "scenarios": scenarios,
        "schema_version": 2,
        # Foglamp WP1 (1C/1D): validity + epistemic labeling. WorldState output
        # is an elicited model projection, never authoritative evidence (I-11).
        "round_accounting": verdict["round_accounting"],
        "validity": verdict["validity"],
        "validity_reasons": verdict["validity_reasons"],  # SIM-1 (additive)
        "forecast_effect": verdict["forecast_effect"],
        "epistemic_status": "elicited_model_projection",
    }
    if validation_summary is not None:
        result["decision_validation"] = validation_summary
    if period_by_round:
        # 带日期轨迹 schema v3（spec §6）；v2 hours 路径原样。converged/converged_at
        # 只是稳定性信号——日历模式从不据此早停，回放始终推演到判定日。
        result["schema_version"] = 3
        result["mode"] = "calendar"
        if calendar_unit:
            result["calendar_unit"] = calendar_unit
        for fk in ("horizon_date", "horizon_source", "horizon_defaulted"):
            if seed.get(fk) is not None:
                result[fk] = seed.get(fk)
    return result
