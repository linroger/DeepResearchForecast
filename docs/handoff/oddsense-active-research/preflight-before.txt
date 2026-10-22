#!/usr/bin/env python3
"""Canonical environment preflight engine for DeepAgentForecast (EXECPLAN2 I-8-0).

`preflight_pipeline()` (in pipeline_orchestrator) and `Config.validate()` already
encode, in Python, the *meaning* of "is this environment ready for a full
research → graph → simulation → report run": the provider→key-env mapping
(``Config.DEERFLOW_KEY_ENV``), placeholder-key detection
(``Config._PLACEHOLDER_VALUES``) and the graph-backend importability check. Yet
``scripts/doctor.sh`` historically re-derived the same logic in bash, and the
POST /run gate + the frontend each had their own view — three sites that drift
the moment a new provider is added to ``PROVIDER_META``.

This module makes Python the single source of truth. It exposes:

  * ``environment_report(mode, model, deep, pull)`` -> a structured dict that
    fuses the cheap ``preflight_pipeline`` errors with Config metadata into a
    list of ``{id, severity, ok, message, fix}`` checks. This is the same
    document the Settings UI can render via ``GET /api/research/preflight?format=full``.
  * ``deep_probes(...)`` -> the bounded, network-touching probes (a 1-token live
    completion against the configured provider + DeerFlow model credential, the
    GRAPHITI_EMBED_MODEL HF-cache presence, and free disk) that the fast/offline
    path deliberately skips.

CLI usage (``backend/.venv/bin/python backend/scripts/preflight.py ...``):

    preflight.py                       # human-readable text, cheap checks only
    preflight.py --json                # structured environment_report() document
    preflight.py --json --mode full    # same, explicit mode (full | research_only)
    preflight.py --deep                # text, + live key / embed-cache / disk probes
    preflight.py --deep --json         # JSONL: one {"level","message"} per probe
                                       #   (the protocol scripts/doctor.sh consumes)
    preflight.py --deep --pull         # also pre-pull a missing embed model (~470MB)
    preflight.py --model minimax       # override the DeerFlow research model checked

Exit codes (severity-driven, shared by every form):
    0 = ready;  1 = at least one blocking problem;  2 = ready but a (deep) probe
    raised a non-blocking warning.

Reuses ``Config.DEERFLOW_KEY_ENV`` / ``Config._PLACEHOLDER_VALUES`` /
``Config.PROVIDER_META`` and ``app.utils.security.validate_safe_url`` so neither
bash nor this CLI ever re-encodes provider routing or the SSRF guard.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

# scripts/ → backend/ → <repo root>. Mirror check_env_drift.py so `app` imports
# resolve whether invoked as `python backend/scripts/preflight.py` from the repo
# root or `python scripts/preflight.py` from inside backend/.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BACKEND = os.path.join(ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.config import Config  # noqa: E402
from app.services.pipeline_orchestrator import preflight_pipeline  # noqa: E402

# Severity ordering: a "bad" check blocks (exit 1); a "warn" only nudges exit to 2.
SEVERITY_OK = "ok"
SEVERITY_WARN = "warn"
SEVERITY_BAD = "bad"


# ---------------------------------------------------------------------------
# Cheap checks → structured report (no network, no token spend).
# ---------------------------------------------------------------------------
def environment_report(
    mode: str = "full",
    model: str | None = None,
    *,
    deep: bool = False,
    pull: bool = False,
) -> dict:
    """Build the structured readiness document (EXECPLAN2 I-8-0).

    The cheap, blocking checks come verbatim from ``preflight_pipeline`` (the
    single source of truth shared with POST /run), so doctor, the run gate and
    the UI can never disagree about whether a run will succeed. The surrounding
    metadata (provider / deerflow_model / graph_backend / venv / dirs) is read
    from Config so a new provider added to PROVIDER_META is reflected for free.

    Args:
        mode: ``full`` | ``research_only`` (research_only skips graph/report/sim
              credential checks, matching preflight_pipeline semantics).
        model: optional DeerFlow research-model override (per-run override case);
               falls back to ``Config.DEERFLOW_MODEL`` when None.
        deep:  when True, append the bounded network/disk probes from
               ``deep_probes`` into ``checks`` (and the document's exit code).
        pull:  with deep, allow pre-downloading a missing embed model.

    Returns a JSON-serialisable dict:
        {provider, deerflow_model, graph_backend, venv_python, deerflow_dir,
         data_dir, embed_model, mode, ready, exit_code, checks:[...]}.
    """
    df_model = (model or getattr(Config, "DEERFLOW_MODEL", "claude") or "claude").strip().lower()

    checks: list[dict] = []

    # The blocking, offline checks — reuse preflight_pipeline so this CLI, the
    # POST /run gate and doctor share one implementation (no three-place drift).
    for i, err in enumerate(preflight_pipeline(mode=mode, model=model)):
        checks.append(
            {
                "id": f"pipeline.{i}",
                "severity": SEVERITY_BAD,
                "ok": False,
                "message": err,
                # preflight_pipeline already embeds the remediation in the
                # message ("运行 ./setup.sh …"); surface it as the fix too.
                "fix": err,
            }
        )

    # Lightweight informational checks the run gate does not block on but which
    # are genuinely useful in a readiness panel: placeholder credentials.
    _append_placeholder_checks(checks, df_model)

    if deep:
        # In-process deep probes (text/json document path). doctor.sh prefers the
        # JSONL streaming form; here we collect them into the same checks list so
        # the structured document is self-contained.
        for level, message in deep_probes(model=model, pull=pull):
            checks.append(
                {
                    "id": f"deep.{len(checks)}",
                    "severity": level,
                    "ok": level == SEVERITY_OK,
                    "message": message,
                    "fix": None,
                }
            )

    exit_code = _exit_code_for(checks)
    return {
        "provider": getattr(Config, "LLM_PROVIDER", None),
        "deerflow_model": df_model,
        "graph_backend": getattr(Config, "GRAPH_BACKEND", None),
        "venv_python": sys.executable,
        "deerflow_dir": getattr(Config, "DEERFLOW_DIR", None),
        "data_dir": getattr(Config, "GRAPHITI_DATA_DIR", None),
        "embed_model": getattr(Config, "GRAPHITI_EMBED_MODEL", None),
        "mode": mode,
        "ready": exit_code != 1,
        "exit_code": exit_code,
        "checks": checks,
    }


def _append_placeholder_checks(checks: list[dict], df_model: str) -> None:
    """Flag .env values left as ``.env.example`` placeholders (e.g. your_api_key).

    A placeholder is functionally "unset" — keeping it means the run dies dozens
    of minutes in. Reuse ``Config._is_placeholder`` / ``_PLACEHOLDER_VALUES`` so
    bash never re-encodes the (richer-than-doctor's-old-two) placeholder set.
    """
    is_placeholder = getattr(Config, "_is_placeholder", None)
    if not callable(is_placeholder):
        return

    # The OpenAI-compatible report/simulation key.
    if is_placeholder(getattr(Config, "LLM_API_KEY", None)):
        checks.append(
            {
                "id": "placeholder.llm_api_key",
                "severity": SEVERITY_BAD,
                "ok": False,
                "message": "LLM_API_KEY 仍是 .env.example 占位符（等同于未配置）",
                "fix": "把 .env 里的 LLM_API_KEY 替换为真实的 Key",
            }
        )

    # The DeerFlow research-model key (if that model needs one).
    key_env = getattr(Config, "DEERFLOW_KEY_ENV", {}).get(df_model)
    if key_env and is_placeholder(os.environ.get(key_env)):
        checks.append(
            {
                "id": f"placeholder.{key_env.lower()}",
                "severity": SEVERITY_BAD,
                "ok": False,
                "message": f"{key_env} 仍是占位符（DEERFLOW_MODEL={df_model} 研究阶段将失败）",
                "fix": f"把 .env 里的 {key_env} 替换为真实的 Key",
            }
        )


# ---------------------------------------------------------------------------
# Deep probes (opt-in: live credentials · embed-model cache · free disk).
# ---------------------------------------------------------------------------
def deep_probes(model: str | None = None, *, pull: bool = False):
    """Yield ``(level, message)`` tuples for the bounded, expensive probes.

    These touch the network / filesystem and so are opt-in (``--deep``). Each is
    bounded (a 1-token completion, a cache lookup, a disk stat) so the whole pass
    stays in the ~15s range — surfacing stale-credential / first-run failures at
    a deliberate gate instead of ~30 min into a run.

    ``level`` is one of ok / warn / bad (mirrors doctor.sh's reporters).
    """
    yield from _probe_llm_provider()
    yield from _probe_deerflow_model(model)
    yield from _probe_embed_model(pull=pull)
    yield from _probe_free_disk()


def _live_openai_compat(label: str, provider: str, api_key, base_url, model):
    """One bounded 1-token completion against an OpenAI-compatible endpoint."""
    if not api_key:
        return (SEVERITY_BAD, f"{label}: 未设置 API Key — 无法实测 {provider}")

    # Reuse the same SSRF guard the settings API runs before any network call.
    try:
        from app.utils.security import validate_safe_url

        validate_safe_url(base_url, block_private=getattr(Config, "APP_BLOCK_PRIVATE_URLS", False))
    except Exception as exc:  # ValueError from the guard, or import failure
        return (SEVERITY_BAD, f"{label}: 拒绝的 base_url（{exc}）")

    try:
        from openai import OpenAI
    except Exception:
        return (SEVERITY_WARN, f"{label}: openai SDK 不可用 — 跳过实测")

    client_kwargs = {"api_key": api_key, "base_url": base_url, "timeout": 25, "max_retries": 0}
    # Kimi-for-coding 网关按 User-Agent 校验 coding-agent 身份（与 settings.py 一致）。
    if provider == "kimi":
        client_kwargs["default_headers"] = {
            "User-Agent": getattr(Config, "LLM_USER_AGENT", "claude-cli/1.0.0")
        }

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    # 推理提供方：实测时关闭推理，避免 reasoning 吃光 max_tokens 导致空 content。
    extra = getattr(Config, "_DISABLE_THINKING_EXTRA_BODY", {}).get(provider)
    if extra:
        kwargs["extra_body"] = extra
    # Kimi K2.7 Code 网关硬校验温度（开推理只接受 1、关推理只接受 0.6），temperature=0 会 400。
    # 与 LLMClient._coerce_temperature 同源，否则 kimi 实测会被误报为不可用。
    if provider == "kimi":
        thinking_disabled = bool(extra and (extra.get("thinking") or {}).get("type") == "disabled")
        kwargs["temperature"] = 0.6 if thinking_disabled else 1.0

    started = time.monotonic()
    try:
        OpenAI(**client_kwargs).chat.completions.create(**kwargs)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        hints = {
            401: "无效或过期的 API Key",
            403: "Key 有效但被拒绝访问（套餐/权限）",
            404: "端点或模型不存在 — 检查 Base URL / 模型名",
            429: "被限流 — Key 可用但额度耗尽",
        }
        hint = hints.get(status) if isinstance(status, int) else None
        # 不回显上游异常原文（可能含内部 URL/路径）；仅给映射后的提示。
        return (SEVERITY_BAD, f"{label}: 实测失败（{hint or '检查 Key / Base URL / 模型名'}）")
    latency = int((time.monotonic() - started) * 1000)
    return (SEVERITY_OK, f"{label}: 实测连通 OK（{model} · {latency}ms）")


def _live_cli(label: str, cli: str):
    """CLI 提供方（claude/codex）：检查 CLI 在 PATH 上（登录凭据运行时实取）。"""
    if shutil.which(cli):
        return (SEVERITY_OK, f"{label}: '{cli}' CLI 在 PATH 上（运行时使用本机登录凭据）")
    return (SEVERITY_BAD, f"{label}: '{cli}' CLI 不在 PATH 上")


def _probe_llm_provider():
    """实测报告/模拟阶段的 LLM 提供方（当前 Config.LLM_PROVIDER）。"""
    provider = (getattr(Config, "LLM_PROVIDER", "") or "").strip().lower()
    meta = (getattr(Config, "PROVIDER_META", {}) or {}).get(provider, {}) or {}
    if not meta:
        yield (SEVERITY_WARN, f"LLM_PROVIDER: 未知提供方 '{provider}' — 跳过实测")
        return
    if not meta.get("openai_compat"):
        yield _live_cli(f"LLM_PROVIDER={provider}", "claude" if provider == "claude-cli" else "codex")
        return
    base = getattr(Config, "LLM_BASE_URL", None) or meta.get("default_base") or "https://api.openai.com/v1"
    model = getattr(Config, "LLM_MODEL_NAME", None) or meta.get("default_model") or "gpt-4o-mini"
    yield _live_openai_compat(
        f"LLM_PROVIDER={provider}", provider, getattr(Config, "LLM_API_KEY", None), base, model
    )


def _probe_deerflow_model(model: str | None):
    """实测研究阶段模型的凭据。DeerFlow 模型名 1:1 映射到 PROVIDER_META，故复用其
    default_base / default_model / key_env，绝不硬编码 URL（DRY + 永不漂移）。"""
    df_model = (model or getattr(Config, "DEERFLOW_MODEL", "") or "claude").strip().lower()
    all_meta = getattr(Config, "PROVIDER_META", {}) or {}
    key_env_map = getattr(Config, "DEERFLOW_KEY_ENV", {}) or {}

    if df_model in ("claude", "codex"):
        yield _live_cli(f"DEERFLOW_MODEL={df_model}", "claude" if df_model == "claude" else "codex")
        return
    if df_model not in all_meta and df_model not in key_env_map:
        yield (SEVERITY_WARN, f"DEERFLOW_MODEL: 未知模型 '{df_model}' — 跳过实测")
        return

    dmeta = all_meta.get(df_model, {})
    key_env = dmeta.get("key_env") or key_env_map.get(df_model, f"{df_model.upper()}_API_KEY")
    key = os.environ.get(key_env) or ""
    base = os.environ.get(f"{df_model.upper()}_BASE_URL") or dmeta.get("default_base") or "https://api.openai.com/v1"
    model_name = os.environ.get(f"{df_model.upper()}_MODEL") or dmeta.get("default_model") or df_model
    if not key:
        yield (SEVERITY_BAD, f"DEERFLOW_MODEL={df_model}: 未设置 {key_env} — 研究阶段将失败")
        return
    yield _live_openai_compat(f"DEERFLOW_MODEL={df_model}", df_model, key, base, model_name)


def _embed_cached(name: str):
    """嵌入模型是否已在 HF cache 里。True/False/None(无法判定)。"""
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return None
    # 裸 sentence-transformers 名解析为 sentence-transformers/<name>。
    repos = [name] if "/" in name else [name, f"sentence-transformers/{name}"]
    markers = ("modules.json", "config_sentence_transformers.json", "config.json")
    for repo in repos:
        for fn in markers:
            try:
                r = try_to_load_from_cache(repo_id=repo, filename=fn)
            except Exception:
                r = None
            # try_to_load_from_cache 命中时返回 str 路径；缺失返回 None；
            # HF 缓存了 "no-exist" 时返回哨兵对象。仅非空 str 才算真正存在。
            if isinstance(r, str) and r:
                return True
    return False


def _probe_embed_model(*, pull: bool):
    """GRAPHITI_EMBED_MODEL 是否已缓存（首跑会下载 ~470MB）。"""
    embed = getattr(Config, "GRAPHITI_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
    cached = _embed_cached(embed)
    if cached is True:
        yield (SEVERITY_OK, f"嵌入模型已缓存: {embed}")
        return
    if cached is None:
        yield (SEVERITY_WARN, f"嵌入模型: 无法检查 {embed} 的 HF 缓存（huggingface_hub 缺失？）")
        return
    if not pull:
        yield (
            SEVERITY_WARN,
            f"嵌入模型 {embed} 不在 HF 缓存中 — 首次建图将下载 ~470MB；"
            f"现在预拉取: bash scripts/doctor.sh --deep --pull",
        )
        return
    yield (SEVERITY_WARN, f"嵌入模型 {embed} 未缓存 — 正在预拉取（~470MB，一次性）…")
    try:
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(embed)  # 下载并缓存；离线/不可达时抛错
        if _embed_cached(embed):
            yield (SEVERITY_OK, f"嵌入模型已拉取并缓存: {embed}")
        else:
            yield (SEVERITY_WARN, f"嵌入模型 {embed} 拉取完成但缓存检查仍为否")
    except Exception as exc:
        yield (
            SEVERITY_BAD,
            f"嵌入模型 {embed} 拉取失败（{type(exc).__name__}）— 需要网络 + ~470MB 空间",
        )


def _gb(n: int) -> str:
    return f"{n / (1024 ** 3):.1f}GB"


def _probe_free_disk():
    """对图数据目录 / uploads 检查可用磁盘。"""
    checked: set[str] = set()
    for label, path in (
        ("GRAPHITI_DATA_DIR", getattr(Config, "GRAPHITI_DATA_DIR", None)),
        ("uploads", getattr(Config, "UPLOAD_FOLDER", None)),
    ):
        if not path:
            continue
        # disk_usage 需要存在的目录；上溯到最近的存在父目录。
        probe = os.path.abspath(path)
        while probe and not os.path.isdir(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if not probe or not os.path.isdir(probe) or probe in checked:
            continue
        checked.add(probe)
        try:
            free = shutil.disk_usage(probe).free
        except Exception as exc:
            yield (SEVERITY_WARN, f"{label}: 无法读取 {path} 的可用磁盘（{type(exc).__name__}）")
            continue
        # 2GB 余量覆盖 ~470MB 嵌入模型 + 图数据库增长 + 报告产物。
        if free < 2 * 1024 ** 3:
            yield (SEVERITY_BAD, f"{label}: {probe} 仅剩 {_gb(free)} — 需要 >=2GB（嵌入模型 + 图数据库）")
        elif free < 5 * 1024 ** 3:
            yield (SEVERITY_WARN, f"{label}: {probe} 剩 {_gb(free)} — 偏紧；建议 >=5GB 留余量")
        else:
            yield (SEVERITY_OK, f"{label}: {probe} 剩 {_gb(free)}")


# ---------------------------------------------------------------------------
# Exit-code + rendering.
# ---------------------------------------------------------------------------
def _exit_code_for(checks: list[dict]) -> int:
    """0 = ready; 1 = a blocking (bad) check; 2 = only warnings."""
    if any(c.get("severity") == SEVERITY_BAD for c in checks):
        return 1
    if any(c.get("severity") == SEVERITY_WARN for c in checks):
        return 2
    return 0


def _render_text(report: dict) -> int:
    """Human-readable colored output (matches doctor.sh's ✓/⚠/✗ vocabulary)."""
    use_color = sys.stdout.isatty()
    reset = "\033[0m" if use_color else ""
    green = "\033[32m" if use_color else ""
    yellow = "\033[33m" if use_color else ""
    red = "\033[31m" if use_color else ""
    bold = "\033[1m" if use_color else ""

    glyph = {SEVERITY_OK: (green, "✓"), SEVERITY_WARN: (yellow, "⚠"), SEVERITY_BAD: (red, "✗")}

    print(f"{bold}== Preflight ({report['mode']}) =={reset}")
    print(
        f"  provider={report.get('provider')}  deerflow_model={report.get('deerflow_model')}  "
        f"graph_backend={report.get('graph_backend')}"
    )
    checks = report.get("checks") or []
    if not checks:
        print(f"{green}✓{reset} 所有启动前检查通过 — 可以起飞")
    for c in checks:
        color, mark = glyph.get(c.get("severity"), (yellow, "⚠"))
        print(f"{color}{mark}{reset} {c.get('message')}")
        fix = c.get("fix")
        if fix and not c.get("ok") and fix != c.get("message"):
            print(f"    → {fix}")

    code = report.get("exit_code", _exit_code_for(checks))
    print()
    if code == 1:
        n_bad = sum(1 for c in checks if c.get("severity") == SEVERITY_BAD)
        print(f"{red}✗{reset} {n_bad} 个阻塞问题 — 修复上面的 ✗ 项后重试")
    elif code == 2:
        print(f"{yellow}⚠{reset} 就绪，但有警告 — 见上面的 ⚠ 项")
    else:
        print(f"{green}✓{reset} 全部通过 — 可以起飞")
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="DeepAgentForecast environment preflight (single source of truth, "
        "shared by doctor.sh / POST /run gate / Settings UI)."
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output (see below)")
    ap.add_argument(
        "--mode",
        choices=("full", "research_only"),
        default="full",
        help="research_only skips graph/report/simulation checks",
    )
    ap.add_argument("--model", default=None, help="override the DeerFlow research model checked")
    ap.add_argument(
        "--deep",
        action="store_true",
        help="add bounded network/disk probes (live key · embed-cache · free disk)",
    )
    ap.add_argument(
        "--pull",
        action="store_true",
        help="with --deep, pre-download a missing embedding model (~470MB)",
    )
    args = ap.parse_args(argv)

    # JSONL streaming contract consumed by scripts/doctor.sh:
    #   `preflight.py --deep --json` emits one {"level","message"} object per
    #   probe line, and the exit code reflects the worst probe. doctor.sh already
    #   ran the cheap checks in bash, so here --deep --json reports only the
    #   deep probes (keeping doctor's rendering authoritative).
    if args.deep and args.json:
        worst = 0
        for level, message in deep_probes(model=args.model, pull=args.pull):
            print(json.dumps({"level": level, "message": message}, ensure_ascii=False))
            sys.stdout.flush()
            if level == SEVERITY_BAD:
                worst = 1
            elif level == SEVERITY_WARN and worst != 1:
                worst = 2
        return worst

    report = environment_report(mode=args.mode, model=args.model, deep=args.deep, pull=args.pull)

    if args.json:
        # Structured environment_report() document (Settings UI / CI gating).
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report["exit_code"]

    return _render_text(report)


if __name__ == "__main__":
    sys.exit(main())
