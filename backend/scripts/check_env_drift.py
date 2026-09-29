#!/usr/bin/env python3
"""Validate that every env var Config reads is documented in .env.example
(EXECPLAN2 I-8-5), and audit the runtime .env for pins that silently override
improved defaults (ENV-1).

Two independent modes:

  (default)  DOC-DRIFT — a knob Config honours but `.env.example` never mentions
             is undiscoverable; a documented knob nothing reads is dead. Wired
             into doctor.sh + CI (`--strict` exits non-zero on drift).

  --pins     PIN-DIVERGENCE — the runtime .env can pin a value that silently
             overrides an improved Config default (live example:
             REPORT_SECTION_CONCURRENCY=1 vs the current default 6, which
             serialises report synthesis). Parses the repo-root .env, compares
             each active pin against (a) the current Config default introspected
             from config.py and (b) the documented .env.example guidance, and
             prints the DIVERGENT pins with a severity hint (performance-critical
             knobs — REPORT_SECTION_CONCURRENCY / DEERFLOW_RESEARCH_DEPTH /
             RESEARCH_PARALLEL_TRACKS / N_FORECAST_SEEDS / ENSEMBLE_SEED_CONCURRENCY
             / OASIS_SEMAPHORE / GRAPH_BUILD_CONCURRENCY … — are flagged loudly),
             and honesty-critical knobs (EVAL-15: REPORT_PUBLISH_GATE /
             REPORT_PUBLISH_GATE_MIN_COVERAGE / REPORT_FINAL_READ_ONLY_AUDIT /
             PIPELINE_HEALTH_GATE — a pin here relaxes a publish/audit/health
             gate, e.g. MIN_COVERAGE=0.05 lets a 0.07-coverage report publish)
             are flagged just as loudly.
             ADVISORY: `--pins` always exits 0; `--pins --strict` exits 1 only
             when a performance- or honesty-critical pin diverges. Secret-looking
             values (KEY/TOKEN/SECRET) are never printed — they are masked.

Usage:
    python backend/scripts/check_env_drift.py [--strict] [--json]
    python backend/scripts/check_env_drift.py --pins [--strict] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(ROOT, "backend", "app", "config.py")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")
ENV_FILE = os.path.join(ROOT, ".env")  # ENV-1：运行时 .env（可能不存在——纯 advisory）

# Env vars that are read elsewhere (Flask/runtime/deerflow) and intentionally not
# all surfaced in .env.example, or are infra-level — exclude from "missing" drift.
_IGNORE = {
    "FLASK_HOST", "FLASK_PORT", "FLASK_DEBUG", "WERKZEUG_RUN_MAIN",
    "PYTHONUNBUFFERED", "PYTHONUTF8", "PYTHONIOENCODING", "TMPDIR", "LOG_LEVEL",
    # ZEP_API_KEY is an internal Graphiti-shim compat sentinel ('local-graphiti'),
    # not a user-facing knob — intentionally absent from .env.example.
    "ZEP_API_KEY",
}

_ENV_READ_RE = re.compile(r"os\.environ(?:\.get\(\s*['\"]([A-Z0-9_]+)['\"]|\[\s*['\"]([A-Z0-9_]+)['\"]\s*\])")
_ENV_DOC_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]+)=", re.M)


# Per-provider dynamic knobs (e.g. LLM_KIMI_DISABLE_THINKING) — documented as a
# pattern (LLM_<PROVIDER>_DISABLE_THINKING) rather than one line per provider.
_IGNORE_PATTERNS = [re.compile(r"^LLM_[A-Z0-9]+_DISABLE_THINKING$")]

# ---------------------------------------------------------------------------
# ENV-1: pin-divergence audit helpers
# ---------------------------------------------------------------------------
# Performance-critical knobs: a divergent pin here materially changes throughput
# or wall-clock (concurrency fan-outs, research depth, ensemble breadth). These
# are flagged loudly and are the ONLY vars that make `--pins --strict` exit 1.
# The list is intentionally curated (not "every int") so the strict gate stays
# meaningful; extend it when a new first-order throughput lever lands.
PERF_CRITICAL_VARS = {
    "REPORT_SECTION_CONCURRENCY",     # 章节合成并行度（live example：pinned 1 vs default 6）
    "DEERFLOW_RESEARCH_DEPTH",        # 深度研究档位（shallow/standard/deep）
    "RESEARCH_PARALLEL_TRACKS",       # 并行研究轨道数
    "N_FORECAST_SEEDS",               # 多种子集成宽度（重跑 sim+report 段）
    "ENSEMBLE_SEED_CONCURRENCY",      # 多种子集成并行度
    "OASIS_SEMAPHORE",                # 模拟内 LLM 并发上限
    "GRAPH_BUILD_CONCURRENCY",        # 建图分片并发
    "GRAPHITI_MAX_COROUTINES",        # Graphiti 抽取协程上限
    "GRAPH_LLM_EXECUTOR_WORKERS",     # 建图 LLM 执行器线程
    "PARALLEL_PROFILE_COUNT",         # 人设并行扇出
    "REPORT_TRANSLATION_CONCURRENCY", # 双语逐章翻译并行度
    "REPORT_SPINE_SELFCONSISTENCY_K", # 预测脊柱自一致抽样次数
    "LLM_HTTP_KEEPALIVE",             # LLM HTTP keepalive 连接上限
}

# EVAL-15: honesty-critical knobs: a divergent pin here relaxes a gate that keeps
# an unaudited, under-cited or broken deliverable from being published as
# completed (live example: REPORT_PUBLISH_GATE_MIN_COVERAGE=0.05 vs the default
# 0.75 let a report with 0.07 citation coverage pass). Flagged as loudly as
# PERF_CRITICAL_VARS and likewise make `--pins --strict` exit 1.
HONESTY_CRITICAL_VARS = {
    "REPORT_PUBLISH_GATE",            # 发布门（覆盖率/概率闭合/兜底情景）
    "REPORT_PUBLISH_GATE_MIN_COVERAGE",  # 发布门定量引用覆盖率阈值
    "REPORT_FINAL_READ_ONLY_AUDIT",   # 成稿只读审计（final_audit.json）
    "PIPELINE_HEALTH_GATE",           # 交付物健康门（空报告/缺 forecast 硬失败）
}

# Mask anything whose NAME looks like a credential — never print its value.
# Match on underscore-delimited SEGMENTS (not raw substring) so real secrets
# (*_KEY / *_TOKEN / SECRET_* / *_PASSWORD) are masked while token-COUNT knobs
# like REPORT_AGENT_SECTION_MAX_TOKENS (segment 'TOKENS', not 'TOKEN') and
# names that merely contain 'KEY' (e.g. MONKEY) are not falsely masked.
_SECRET_SEGMENTS = {"KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "CREDENTIALS"}

# Extract `os.environ.get('VAR', 'default')` literals from config.py source text.
# re.S so the whitespace gap tolerates the multi-line `.get(\n 'VAR',\n 'default')`
# form (e.g. APP_CORS_ORIGINS). The default literal itself is single-line and
# quote-free internally ([^'\"]*), which covers every default in config.py.
_CONFIG_DEFAULT_RE = re.compile(
    r"os\.environ\.get\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]\s*,\s*(['\"])([^'\"]*)\2",
    re.S,
)


def config_env_vars() -> set:
    text = open(CONFIG, encoding="utf-8").read()
    out = set()
    for m in _ENV_READ_RE.finditer(text):
        out.add(m.group(1) or m.group(2))
    out -= _IGNORE
    return {v for v in out if not any(p.match(v) for p in _IGNORE_PATTERNS)}


def documented_env_vars() -> set:
    if not os.path.exists(ENV_EXAMPLE):
        return set()
    text = open(ENV_EXAMPLE, encoding="utf-8").read()
    return set(_ENV_DOC_RE.findall(text))


def config_defaults(text: str | None = None) -> dict:
    """var -> default literal string, introspected from config.py source text
    the same way config_env_vars() does (regex over source — no import, so this
    stays offline and needs no backend deps). First occurrence wins (the real
    assignment precedes any doc-comment mention). Vars whose `os.environ.get`
    has no default literal (or use os.environ[...]) are simply absent here."""
    if text is None:
        text = open(CONFIG, encoding="utf-8").read()
    out: dict = {}
    for m in _CONFIG_DEFAULT_RE.finditer(text):
        var = m.group(1)
        if var not in out:                # first (real) definition wins
            out[var] = m.group(3)
    return out


def parse_env_text(text: str) -> dict:
    """Parse ACTIVE (uncommented) assignments from .env-style text.

    Mirrors python-dotenv / doctor.sh envval(): honours an optional `export `
    prefix, strips surrounding matching quotes, and strips a space-prefixed
    inline comment ( # ...) only when the value is unquoted — so `sk-abc#x`
    stays intact but `foo  # note` → `foo`. Later assignments win (last wins,
    matching dotenv override semantics)."""
    out: dict = {}
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[len("export "):].lstrip()
        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]                       # quoted: keep as-is inside quotes
        else:
            val = re.sub(r"\s+#.*$", "", val).strip()  # unquoted: drop inline comment
        out[key] = val
    return out


def parse_env_file(path: str) -> dict:
    """parse_env_text() over a file on disk. Missing file → empty dict."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return parse_env_text(fh.read())


def example_values(text: str | None = None) -> dict:
    """var -> documented value from ACTIVE (uncommented) .env.example lines.
    These are the recommended/shipped defaults .env.example commits to; used as
    the fallback reference when config.py exposes no default literal for a pin."""
    if text is None:
        if not os.path.exists(ENV_EXAMPLE):
            return {}
        text = open(ENV_EXAMPLE, encoding="utf-8").read()
    return parse_env_text(text)


def is_secret(var: str) -> bool:
    """True if the var NAME looks like a credential (mask its value on output).
    Segment-exact so a token-COUNT knob (…_MAX_TOKENS) is NOT masked but every
    genuine *_KEY / *_TOKEN / SECRET_* / *_PASSWORD credential is."""
    return any(seg in _SECRET_SEGMENTS for seg in (var or "").upper().split("_"))


def mask_value(var: str, value: str) -> str:
    """Never surface secret values: a KEY/TOKEN/SECRET var renders as '***'."""
    if is_secret(var):
        return "***"
    return "" if value is None else str(value)


def _normalize(v) -> str:
    """Compare pins to defaults up to trivial formatting: strip whitespace + one
    layer of surrounding quotes, and fold boolean literals case-insensitively
    (config reads them via .strip().lower()=='true', so True==true). Everything
    else stays case/character exact (model names / URLs / paths are sensitive)."""
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    low = s.lower()
    if low in ("true", "false"):
        return low
    return s


def find_divergent_pins(env_path: str | None = None,
                        config_text: str | None = None,
                        example_text: str | None = None) -> list:
    """Return the list of .env pins whose value diverges from the current
    reference default. Reference default = config.py default literal if known,
    else the documented .env.example value. Pins are skipped when:
      * the var is infra-level (_IGNORE),
      * no reference default can be determined (nothing to override),
      * the reference default is empty ('' means "unset by default" — pinning an
        API key / URL is expected, not a downgrade of an improved default), or
      * the normalised values match.
    Records carry MASKED values (secrets never leak). Critical-first ordering."""
    if env_path is None:
        env_path = ENV_FILE
    defaults = config_defaults(config_text)
    examples = example_values(example_text)
    pins = parse_env_file(env_path)

    out: list = []
    for var, pinned in pins.items():
        if var in _IGNORE:
            continue
        source = "config"
        default = defaults.get(var)
        if default is None:
            default = examples.get(var)
            source = "env.example"
        if default is None:
            continue                       # unknown reference — cannot judge
        if default.strip() == "":
            continue                       # empty default = unset-by-default; pin is expected
        if _normalize(pinned) == _normalize(default):
            continue                       # matches default — not divergent
        out.append({
            "var": var,
            "pinned": mask_value(var, pinned),
            "current_default": mask_value(var, default),
            "default_source": source,
            "critical": var in PERF_CRITICAL_VARS,
            "honesty_critical": var in HONESTY_CRITICAL_VARS,
            "secret": is_secret(var),
        })
    # Loud items first (performance- or honesty-critical), then alphabetical for stability.
    out.sort(key=lambda r: (not _is_loud(r), r["var"]))
    return out


def _is_loud(record: dict) -> bool:
    """A pin that is flagged loudly and fails `--pins --strict`."""
    return bool(record.get("critical") or record.get("honesty_critical"))


def _render_pins(divergent: list, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"divergent_pins": divergent,
                          "critical_count": sum(1 for r in divergent if r["critical"]),
                          "honesty_critical_count": sum(
                              1 for r in divergent if r.get("honesty_critical"))},
                         indent=2, ensure_ascii=False))
        return
    if not divergent:
        print("✓ no .env pins diverge from current Config defaults")
        return
    crit = [r for r in divergent if r["critical"]]
    honesty = [r for r in divergent if r.get("honesty_critical")]
    print(f"⚠️  {len(divergent)} .env pin(s) diverge from current Config defaults"
          f" ({len(crit)} performance-critical, {len(honesty)} honesty-critical):")
    # column widths (over masked values, so no secret influences layout)
    wv = max(3, max(len(r["var"]) for r in divergent))
    wp = max(6, max(len(r["pinned"]) for r in divergent))
    wd = max(7, max(len(r["current_default"]) for r in divergent))
    print(f"    {'':3}{'VAR'.ljust(wv)}  {'PINNED'.ljust(wp)}  {'DEFAULT'.ljust(wd)}  SOURCE")
    for r in divergent:
        marker = "‼  " if r["critical"] else ("‼H " if r.get("honesty_critical") else "   ")
        print(f"    {marker}{r['var'].ljust(wv)}  {r['pinned'].ljust(wp)}  "
              f"{r['current_default'].ljust(wd)}  {r['default_source']}")
    if crit:
        print("    ‼ = performance-critical: this pin overrides an improved default and "
              "may throttle throughput/quality.")
    if honesty:
        print("    ‼H = honesty-critical: this pin relaxes a publish/audit/health gate, so "
              "under-cited or unaudited reports can publish as completed.")
    if crit or honesty:
        print("      Remove the pin (or align it) unless the override is deliberate.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pins", action="store_true",
                   help="ENV-1: audit repo-root .env for pins that diverge from current Config defaults (advisory)")
    ap.add_argument("--strict", action="store_true",
                   help="doc-drift: exit 1 if any Config var is undocumented; with --pins: exit 1 only if a performance- or honesty-critical pin diverges")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.pins:
        # ENV-1 advisory pin audit. Always exit 0 unless --strict AND a
        # performance- or honesty-critical pin diverges (never blocks the default run).
        divergent = find_divergent_pins()
        _render_pins(divergent, args.json)
        loud = any(_is_loud(r) for r in divergent)
        return 1 if (args.strict and loud) else 0

    read = config_env_vars()
    documented = documented_env_vars()
    missing = sorted(read - documented)          # read by Config, not in .env.example
    undocumented_ok = sorted(documented - read)  # in .env.example, not read by Config (informational)

    if args.json:
        print(json.dumps({"missing_from_env_example": missing,
                          "documented_but_unread": undocumented_ok}, indent=2))
    else:
        if missing:
            print("⚠️  Config reads these env vars but .env.example does not document them:")
            for k in missing:
                print(f"    - {k}")
        else:
            print("✓ every Config env var is documented in .env.example")
        if undocumented_ok:
            print("ℹ️  documented in .env.example but not read by Config (may be for subprocesses):")
            print("    " + ", ".join(undocumented_ok))

    return 1 if (args.strict and missing) else 0


if __name__ == "__main__":
    sys.exit(main())
