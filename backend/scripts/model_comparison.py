#!/usr/bin/env python3
"""Model-comparison harness: same forecast, multiple LLM providers (EXECPLAN2 I-9-4).

Runs the *same* question through several LLM providers and presents a side-by-side
comparison of their structured forecasts. The cheap, high-signal variant fixes one
completed OASIS simulation (research + graph + sim are shared) and re-runs only the
REPORT stage under each provider — where provider reasoning quality shows most —
then extracts a structured forecast per provider and aggregates a per-scenario
table of (provider -> probability) plus an inter-provider agreement score.

Why this matters: provider quality varies enormously for reasoning-heavy synthesis,
and users have no evidence for which to trust on their kind of question. Surfacing
model disagreement is itself an uncertainty signal — if 3 models agree on a
probability that is far stronger than one model's guess.

OPTIONAL-DEGRADE invariant: this is an opt-in, off-by-default capability. It is a
standalone script (nothing in the running pipeline calls it) and additionally
gated behind Config.MODEL_COMPARISON_ENABLED (read via getattr; default False) so
that wiring it into an API later stays disabled unless explicitly turned on. The
global Config.LLM_PROVIDER and every existing single-provider run are untouched:
each provider is driven through a *per-instance* LLMClient(provider=...) override,
not by mutating the global default.

Structural prerequisite (already satisfied): LLMClient.__init__ already accepts
per-instance (provider, api_key, base_url, model) overrides, and ReportAgent.__init__
already accepts an llm_client — so this harness is pure wiring, no signature change.

Examples:
    # compare three providers on a finished pipeline's simulation (report-only rerun)
    python backend/scripts/model_comparison.py compare <pipeline_id> \
        --providers claude-cli deepseek glm -o comparison.json

    # list which providers currently have working credentials (no run)
    python backend/scripts/model_comparison.py providers
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

# scripts/ -> backend/ on sys.path (mirror of scripts/forecast_tools.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services.ensemble import aggregate_forecasts  # noqa: E402
from app.services.forecast_extractor import (  # noqa: E402
    audit_citation_grounding,
    extract_structured_forecast,
    self_critique_forecast,
)
from app.services.pipeline_orchestrator import (  # noqa: E402
    PipelineManager,
    load_research_dossier_for_simulation,
)
from app.services.report_agent import ReportAgent, ReportManager, ReportStatus  # noqa: E402
from app.utils.atomic import write_text_atomic  # noqa: E402
from app.utils.llm_client import LLMClient  # noqa: E402
from app.utils.logger import get_logger  # noqa: E402
from app.utils.telemetry import LLMMeter, set_run_context  # noqa: E402

logger = get_logger("mirofish.model_comparison")

# 提供方名只允许字母/数字/下划线/连字符（用于安全拼接报告文件夹名，杜绝路径穿越）。
_PROVIDER_RE = re.compile(r"^[a-z0-9_-]+$")


# ----------------------------------------------------------------------------- credentials
def provider_credentials_ok(provider: str, api_key: Optional[str] = None) -> Tuple[bool, str]:
    """轻量本地凭据体检：该提供方现在能跑吗？（不发任何网络请求）

    复用 preflight_pipeline 的判定口径（PROVIDER_META.needs_key + CLI 二进制在 PATH）：
      - CLI 提供方（claude-cli/codex-cli）：对应可执行文件必须在 PATH 上。
      - OpenAI 兼容提供方：需要一个 Key——优先 --api-key，其次（当它正好是全局 provider 时）
        Config.LLM_API_KEY，再次该提供方专属环境变量（PROVIDER_META[...]['key_env']）。

    Returns (ok, reason)；ok=False 时 reason 是人类可读的缺失说明，供 --skip-unavailable 过滤。
    """
    provider = (provider or "").strip().lower()
    meta = Config.PROVIDER_META.get(provider)
    if meta is None:
        return False, f"未知提供方: {provider!r}"

    if not meta.get("openai_compat"):
        # CLI / 订阅类提供方：仅需对应 CLI 在 PATH（凭据走本机订阅 OAuth/Keychain）。
        binary = "claude" if provider == "claude-cli" else "codex" if provider == "codex-cli" else None
        if binary and shutil.which(binary) is None:
            return False, f"未找到 `{binary}` CLI（安装后重试，或改用其它提供方）"
        return True, "ok"

    # OpenAI 兼容提供方：必须有可用 Key。
    if (api_key or "").strip():
        return True, "ok"
    if provider == Config.LLM_PROVIDER and Config.LLM_API_KEY:
        return True, "ok"
    key_env = meta.get("key_env")
    if key_env and os.environ.get(key_env, "").strip():
        return True, "ok"
    # 全局 provider 即此提供方但未配 Key 的情况已在上面返回 False；这里给出最有用的提示。
    hint = f"设置 {key_env} 或传 --api-key" if key_env else "设置 LLM_API_KEY 或传 --api-key"
    return False, f"提供方 {provider} 需要 API Key（{hint}）"


def _build_client_for(provider: str, api_key: Optional[str] = None) -> LLMClient:
    """为单个提供方构造一个 per-instance LLMClient（绝不触碰全局 Config.LLM_PROVIDER）。

    OpenAI 兼容提供方未显式传 Key 时，回退到 Config.LLM_API_KEY（当它正好是当前全局 provider）
    或该提供方专属环境变量；base_url/model 缺省走 PROVIDER_META 的默认连接参数，与
    Config.apply_provider 的默认口径一致。
    """
    provider = (provider or "").strip().lower()
    meta = Config.PROVIDER_META.get(provider, {})
    kwargs: Dict[str, Any] = {"provider": provider}
    if meta.get("openai_compat"):
        key = (api_key or "").strip()
        if not key and provider == Config.LLM_PROVIDER:
            key = (Config.LLM_API_KEY or "").strip()
        if not key:
            key_env = meta.get("key_env")
            if key_env:
                key = os.environ.get(key_env, "").strip()
        if key:
            kwargs["api_key"] = key
        # base_url/model 缺省用提供方默认，避免误用全局 Config（可能指向另一个 OpenAI 兼容端点）。
        if provider != Config.LLM_PROVIDER:
            if meta.get("default_base"):
                kwargs["base_url"] = meta["default_base"]
            if meta.get("default_model"):
                kwargs["model"] = meta["default_model"]
    return LLMClient(**kwargs)


# ----------------------------------------------------------------------------- base run loading
def _load_base_context(base_pipeline_id: str) -> Dict[str, Any]:
    """加载基线管线的共享上下文（graph_id/simulation_id/prompt + 研究档案）。

    要求基线模拟已完成（有 simulation_id 与 graph_id）；否则无可对比的共享底座。
    研究档案（situation_brief/actors/sources/research_report）best-effort 复用 T4.1 的
    load_research_dossier_for_simulation，缺失时报告退回冷图盲搜路径（与旧行为一致）。
    """
    data = PipelineManager.load(base_pipeline_id)
    if not data:
        raise ValueError(f"未找到基线管线: {base_pipeline_id!r}")
    simulation_id = data.get("simulation_id")
    graph_id = data.get("graph_id")
    prompt = data.get("prompt") or data.get("simulation_requirement") or ""
    if not simulation_id or not graph_id:
        raise ValueError(
            f"基线管线 {base_pipeline_id!r} 的模拟尚未完成"
            f"（simulation_id={simulation_id!r} graph_id={graph_id!r}）；"
            "请先跑完一次完整管线再做模型对比。"
        )
    if not prompt:
        raise ValueError(f"基线管线 {base_pipeline_id!r} 缺少 prompt/simulation_requirement")

    dossier = load_research_dossier_for_simulation(simulation_id)
    return {
        "base_pipeline_id": base_pipeline_id,
        "simulation_id": simulation_id,
        "graph_id": graph_id,
        "prompt": prompt,
        "situation_brief": dossier.get("situation_brief"),
        "actors": dossier.get("actors"),
        "sources": dossier.get("sources"),
        "research_report": dossier.get("research_report"),
    }


def _safe_report_id(base_pipeline_id: str, provider: str) -> str:
    """确定性、可安全用作文件夹名的对比报告 id：cmp__<base>__<provider>__<rand8>。

    base/provider 都做白名单清洗（仅 [a-z0-9_-]），杜绝来自管线 id/提供方名的路径穿越；
    加 8 位随机后缀避免对同一 (base, provider) 重复对比时覆盖上一份。
    """
    safe_base = re.sub(r"[^A-Za-z0-9_-]", "-", str(base_pipeline_id))[:48]
    safe_prov = re.sub(r"[^a-z0-9_-]", "-", str(provider).lower())[:24]
    return f"cmp__{safe_base}__{safe_prov}__{uuid.uuid4().hex[:8]}"


# ----------------------------------------------------------------------------- per-provider report
def _run_report_for_provider(
    ctx: Dict[str, Any],
    provider: str,
    api_key: Optional[str],
    *,
    self_critique: bool,
) -> Dict[str, Any]:
    """在共享模拟上，用指定提供方重跑 REPORT 阶段并抽取结构化预测。

    流程（与 PipelineOrchestrator 的 report 阶段同口径，仅把 llm_client 换成 per-provider）：
      1) 用 per-instance LLMClient(provider=...) 构造 ReportAgent（钉入研究档案）。
      2) generate_report() 生成散文报告（落到 cmp__<base>__<provider>__<rand> 报告文件夹）。
      3) 用同一 provider 客户端抽取结构化预测（forecast.json），可选红队自校准。
    Returns 单个提供方的结果记录（含 forecast / 报告路径 / 计量 / 错误）。
    """
    report_id = _safe_report_id(ctx["base_pipeline_id"], provider)
    run_id = f"compare__{report_id}"
    result: Dict[str, Any] = {
        "provider": provider,
        "report_id": report_id,
        "ok": False,
        "error": None,
        "forecast": None,
        "report_path": None,
        "telemetry": None,
    }
    try:
        client = _build_client_for(provider, api_key)
    except Exception as exc:  # 构造失败（如缺 Key）——记录并跳过该提供方，不影响其它。
        result["error"] = f"LLMClient 构造失败: {exc}"
        logger.warning("[%s] 跳过提供方 %s：%s", ctx["base_pipeline_id"], provider, exc)
        return result

    # 计量隔离：每个提供方用独立 run_id，token/成本/延迟互不串扰；落各自报告文件夹。
    set_run_context(run_id, "report")
    try:
        agent = ReportAgent(
            graph_id=ctx["graph_id"],
            simulation_id=ctx["simulation_id"],
            simulation_requirement=ctx["prompt"],
            llm_client=client,
            situation_brief=ctx.get("situation_brief"),
            actors=ctx.get("actors"),
            sources=ctx.get("sources"),
            research_report=ctx.get("research_report"),
        )
        # EVAL-1: 提供方对比重跑是同一问题的重复作答——以 comparison 入账，不进生产校准；
        # provider 区分各提供方的目标键（彼此不是修订关系）。
        agent.ledger_context = {
            "pipeline_id": ctx["base_pipeline_id"],
            "simulation_id": ctx["simulation_id"],
            "record_class": "comparison",
            "run_kind": "model_comparison",
            "provider": provider,
        }

        def _cb(stage: str, progress: int, message: str) -> None:
            logger.info("[%s] %s: %s (%s%%)", provider, stage, message, progress)

        report = agent.generate_report(progress_callback=_cb, report_id=report_id)
        if getattr(report, "status", None) == ReportStatus.FAILED:
            raise RuntimeError(getattr(report, "error", None) or "报告生成失败")

        markdown = getattr(report, "markdown_content", "") or ""
        result["report_path"] = ReportManager._get_report_markdown_path(report_id)

        # 结构化预测抽取（用同一 provider 客户端，让“预测对象”也由被评测的模型产出）。
        # 不依赖全局 REPORT_STRUCTURED_FORECAST 开关——对比恒需结构化对象才有可比性。
        forecast = extract_structured_forecast(
            markdown, client, situation_brief=ctx.get("situation_brief")
        )
        if self_critique:
            forecast = self_critique_forecast(forecast, client)
        forecast["citation_audit"] = audit_citation_grounding(markdown)
        forecast["provider"] = provider
        # 落 forecast.json 到该提供方的报告文件夹，便于后续用 forecast_tools.py 复算。
        fpath = os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")
        write_text_atomic(fpath, json.dumps(forecast, ensure_ascii=False, indent=2))

        result["forecast"] = forecast
        result["telemetry"] = LLMMeter.snapshot(run_id)
        result["ok"] = True
        logger.info(
            "[%s] 完成：%d 情景，引用覆盖 %s",
            provider,
            len(forecast.get("scenarios", [])),
            forecast.get("citation_audit", {}).get("coverage"),
        )
    except Exception as exc:  # noqa: BLE001 — 单个提供方失败绝不拖垮整次对比
        result["error"] = str(exc)
        logger.error("[%s] 报告/预测失败（已隔离）: %s", provider, exc, exc_info=True)
    finally:
        set_run_context(None, None)
        LLMMeter.reset(run_id)
    return result


# ----------------------------------------------------------------------------- aggregation
def _norm_name(name: Any) -> str:
    """与 ensemble._norm_name 同口径的松散情景名归一化（跨提供方对齐同名情景）。"""
    return re.sub(r"\s+", " ", re.sub(r"[^\w一-鿿]+", " ", str(name or "").lower())).strip()


def build_comparison(base_pipeline_id: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把多提供方的结构化预测拼成一张可对比的表 + 一致性度量。

    - per_scenario：每个（归一化后对齐的）情景一行，列出各提供方的概率；并给出
      mean/spread（stdev/min/max）与覆盖该情景的提供方数，复用 aggregate_forecasts。
    - agreement：复用 ensemble 的“1 - 2×平均 spread”一致性分（[0,1]，越高分歧越小）。
      高一致性 = 更强的不确定性信号（多个模型独立得出相近概率）。
    - confidence_by_provider：各提供方对整体预测的自评信心（low/medium/high）。
    只统计成功的提供方；失败的列在 failed 里，不污染聚合。
    """
    ok = [r for r in results if r.get("ok") and isinstance(r.get("forecast"), dict)]
    failed = [
        {"provider": r["provider"], "error": r.get("error") or "unknown"}
        for r in results
        if not r.get("ok")
    ]
    forecasts = [r["forecast"] for r in ok]

    # 复用 ensemble 聚合做 spread/agreement；它按归一化情景名跨“多次运行”聚合——
    # 此处“多次运行”即“多个提供方”，语义恰好契合（每个提供方贡献一组情景概率）。
    agg = aggregate_forecasts(forecasts)
    agg_by_name = {_norm_name(s["name"]): s for s in agg.get("scenarios", [])}

    provider_names = [r["provider"] for r in ok]
    per_scenario: List[Dict[str, Any]] = []
    for key, bucket in agg_by_name.items():
        row: Dict[str, Any] = {
            "scenario": bucket.get("name"),
            "mean_probability": bucket.get("mean_probability"),
            "stdev": bucket.get("stdev"),
            "min": bucket.get("min"),
            "max": bucket.get("max"),
            "support": bucket.get("support"),
            "support_ratio": bucket.get("support_ratio"),
            "resolution_criteria": bucket.get("resolution_criteria"),
            "by_provider": {},
        }
        for r in ok:
            prob = None
            for s in (r["forecast"].get("scenarios") or []):
                if _norm_name(s.get("name")) == key:
                    try:
                        prob = round(float(s.get("probability") or 0.0), 4)
                    except (TypeError, ValueError):
                        prob = None
                    break
            row["by_provider"][r["provider"]] = prob
        per_scenario.append(row)
    per_scenario.sort(key=lambda x: (x.get("mean_probability") or 0.0), reverse=True)

    return {
        "base_pipeline_id": base_pipeline_id,
        "providers": provider_names,
        "n_providers": len(provider_names),
        "agreement": agg.get("agreement"),
        "headline": agg.get("headline", ""),
        "horizon": agg.get("horizon", ""),
        "per_scenario": per_scenario,
        "confidence_by_provider": {
            r["provider"]: r["forecast"].get("confidence") for r in ok
        },
        "citation_coverage_by_provider": {
            r["provider"]: (r["forecast"].get("citation_audit") or {}).get("coverage") for r in ok
        },
        "report_paths": {r["provider"]: r.get("report_path") for r in ok},
        # 修复（B16）：此前 per-provider 的延迟/tokens/成本被 LLMMeter 采集了却从未在对比输出里
        # 暴露——"便宜、可计量"的卖点缺了成本维。这里把每家的计量总计切片 surfacing 出来。
        "telemetry_by_provider": {r["provider"]: _telemetry_summary(r.get("telemetry")) for r in ok},
        "failed": failed,
        "schema_version": 1,
    }


def _telemetry_summary(snap):
    """从 LLMMeter 快照取出"总计"切片（surfacing per-provider 成本/延迟/tokens）。无效→None。"""
    if not isinstance(snap, dict):
        return None
    return snap.get("total") or snap


# ----------------------------------------------------------------------------- public API
def compare_models(
    base_pipeline_id: str,
    providers: List[str],
    *,
    api_keys: Optional[Dict[str, str]] = None,
    skip_unavailable: bool = True,
    self_critique: bool = False,
) -> Dict[str, Any]:
    """在一个已完成模拟上，对多个提供方重跑 REPORT 并产出 side-by-side 对比（I-9-4）。

    Args:
        base_pipeline_id: 提供共享 research/graph/simulation 的基线管线 id（其模拟须已完成）。
        providers: 要对比的提供方 id 列表（PROVIDER_META 的键）；去重保序。
        api_keys: 可选 {provider: api_key} 覆盖（不写 .env、不改全局）。
        skip_unavailable: True（默认）时跳过凭据体检不过的提供方；False 时把它们记为失败项。
        self_critique: True 时对每份结构化预测追加一遍红队自校准（多一次 LLM 调用）。

    Returns 对比对象（见 build_comparison）；每个提供方的散文报告 + forecast.json 落各自
    报告文件夹（cmp__<base>__<provider>__<rand>），互不覆盖。
    """
    api_keys = api_keys or {}
    # 去重保序，并做提供方名白名单校验（防御来自调用方的脏输入）。
    seen: set[str] = set()
    clean_providers: List[str] = []
    for p in providers:
        p = (p or "").strip().lower()
        if not p or p in seen:
            continue
        if not _PROVIDER_RE.match(p):
            logger.warning("忽略非法提供方名: %r", p)
            continue
        seen.add(p)
        clean_providers.append(p)
    if not clean_providers:
        raise ValueError("未提供任何有效的对比提供方")

    ctx = _load_base_context(base_pipeline_id)

    results: List[Dict[str, Any]] = []
    for provider in clean_providers:
        key = api_keys.get(provider)
        ok, reason = provider_credentials_ok(provider, key)
        if not ok:
            if skip_unavailable:
                logger.warning("跳过提供方 %s（凭据不可用）：%s", provider, reason)
                continue
            results.append(
                {"provider": provider, "ok": False, "error": f"凭据不可用：{reason}",
                 "forecast": None, "report_path": None, "report_id": None, "telemetry": None}
            )
            continue
        # CLI 提供方不能廉价并发；HTTP 提供方此处也逐个跑（成本随提供方数线性增长，
        # 由调用方显式选择提供方集来控制）。顺序执行最稳，符合 risk note 的缓解策略。
        results.append(
            _run_report_for_provider(ctx, provider, key, self_critique=self_critique)
        )

    return build_comparison(base_pipeline_id, results)


# ----------------------------------------------------------------------------- CLI
def cmd_compare(args: argparse.Namespace) -> int:
    # 双保险开关：默认关。仅当 Config.MODEL_COMPARISON_ENABLED 或 --force 显式打开时才跑。
    # （脚本本身已是 opt-in；此 gate 让“将来接入 API”默认保持关闭，符合 OPTIONAL-DEGRADE。）
    enabled = bool(getattr(Config, "MODEL_COMPARISON_ENABLED", False))
    if not enabled and not args.force:
        print(
            "模型对比默认关闭（OPTIONAL-DEGRADE）。设 MODEL_COMPARISON_ENABLED=true，"
            "或加 --force 显式启用本次运行。",
            file=sys.stderr,
        )
        return 3

    api_keys: Dict[str, str] = {}
    for item in (args.api_key or []):
        if "=" not in item:
            print(f"--api-key 需为 provider=key 形式，收到: {item!r}", file=sys.stderr)
            return 2
        prov, _, key = item.partition("=")
        api_keys[prov.strip().lower()] = key.strip()

    try:
        comparison = compare_models(
            args.pipeline_id,
            args.providers,
            api_keys=api_keys or None,
            skip_unavailable=not args.no_skip_unavailable,
            self_critique=args.self_critique,
        )
    except ValueError as exc:
        print(f"对比失败：{exc}", file=sys.stderr)
        return 2

    out = json.dumps(comparison, ensure_ascii=False, indent=2)
    if args.out:
        write_text_atomic(args.out, out)
        print(
            f"wrote {args.out} "
            f"({comparison['n_providers']} providers, "
            f"{len(comparison['per_scenario'])} scenarios, "
            f"agreement={comparison['agreement']})"
        )
        if comparison["failed"]:
            print(f"  {len(comparison['failed'])} provider(s) failed/skipped: "
                  f"{[f['provider'] for f in comparison['failed']]}", file=sys.stderr)
    else:
        print(out)
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    """列出所有提供方及其当前凭据可用性（不发网络请求、不跑任何报告）。"""
    rows = []
    for pid in Config.PROVIDER_META:
        ok, reason = provider_credentials_ok(pid)
        rows.append({"provider": pid, "available": ok, "reason": reason})
    print(json.dumps({"providers": rows}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="model-comparison harness: same forecast across multiple LLM providers (I-9-4)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser(
        "compare",
        help="re-run REPORT under each provider on a finished pipeline's simulation and compare",
    )
    c.add_argument("pipeline_id", help="基线管线 id（其模拟须已完成；共享 research/graph/sim）")
    c.add_argument(
        "--providers", nargs="+", required=True,
        help="要对比的提供方 id（如 claude-cli deepseek glm）",
    )
    c.add_argument("-o", "--out", default=None, help="对比结果 JSON 输出路径（缺省打印到 stdout）")
    c.add_argument(
        "--api-key", action="append", default=[], metavar="provider=key",
        help="为某提供方临时提供 API Key（不写 .env、不改全局；可多次）",
    )
    c.add_argument(
        "--no-skip-unavailable", action="store_true",
        help="不跳过凭据不可用的提供方，而是把它们记为失败项",
    )
    c.add_argument(
        "--self-critique", action="store_true",
        help="对每份结构化预测追加一遍红队自校准（多一次 LLM 调用）",
    )
    c.add_argument(
        "--force", action="store_true",
        help="忽略 MODEL_COMPARISON_ENABLED 开关，强制本次启用",
    )
    c.set_defaults(func=cmd_compare)

    p = sub.add_parser("providers", help="列出各提供方当前凭据可用性（不跑任何报告）")
    p.set_defaults(func=cmd_providers)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
