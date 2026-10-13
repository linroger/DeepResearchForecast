#!/usr/bin/env bash
#
# doctor.sh — DeepAgentForecast environment health check
# ---------------------------------------------------------------------------
# Verifies, in seconds, everything a full "one prompt -> forecast" run needs:
# tool versions, both Python venvs, the DeerFlow checkout + bridge overlay, the
# official-data MCP servers (datamcps/), and the .env credentials for the
# providers you have selected.
#
#   npm run doctor        (or: bash scripts/doctor.sh)
#
# The default run is intentionally OFFLINE, FREE and INSTANT — it only inspects
# files / PATH / env vars and never touches the network or spends a token.
#
# EXECPLAN2 I-8-2: opt-in `--deep` adds the bounded, expensive checks the fast
# path deliberately skips, so the costliest first-run / stale-credential
# failures surface in a deliberate gate (~15s; up to ~2 min with the data probe) instead of ~30 min into a run:
#   * a 1-token live completion against the configured LLM_PROVIDER (and the
#     DEERFLOW_MODEL credential) to catch bad / expired keys;
#   * verify the GRAPHITI_EMBED_MODEL (~470MB) is present in the HF cache, so an
#     offline first run fails at the gate instead of deep inside the graph build
#     (add `--pull` to pre-download it when absent and online);
#   * a free-disk check against GRAPHITI_DATA_DIR / uploads;
#   * a live official-data probe (advisory, up to ~90s): every enabled data
#     MCP server's handshake plus one cache-first catalog sample (BLS handshake
#     only, so its keyless daily quota is never spent); key names, never values.
#
#   bash scripts/doctor.sh            # fast, offline, free  (default)
#   bash scripts/doctor.sh --deep     # + live key / model-cache / disk / data probes
#   bash scripts/doctor.sh --deep --pull   # also pre-pull a missing embed model
#
# Exit code: 0 = ready to run; 1 = at least one blocking problem; 2 = no
# blocking problem but a --deep probe raised a warning (e.g. un-cached model).
# ---------------------------------------------------------------------------
set -u

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")/.." && pwd)"

# EXECPLAN2 I-8-2: argument parsing. --deep is opt-in so the default contract
# (offline / free / instant) is preserved; --pull only matters with --deep and
# gates a surprise ~470MB embedding download behind an explicit flag.
DEEP=0
PULL=0
for arg in "$@"; do
  case "$arg" in
    --deep)        DEEP=1 ;;
    --pull)        PULL=1 ;;
    -h|--help)
      # Print the header doc block (lines 3-34, between the rule lines) verbatim,
      # stripping the leading "# " so it reads as plain help text.
      sed -n '3,34p' "$SCRIPT_SOURCE" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) printf 'doctor.sh: unknown option %s (try --deep, --pull, --help)\n' "$arg" >&2; exit 64 ;;
  esac
done

if [ -t 1 ]; then
  C_RESET="$(printf '\033[0m')"; C_GREEN="$(printf '\033[32m')"
  C_YELLOW="$(printf '\033[33m')"; C_RED="$(printf '\033[31m')"; C_BOLD="$(printf '\033[1m')"
else
  C_RESET="" C_GREEN="" C_YELLOW="" C_RED="" C_BOLD=""
fi

FAILURES=0
WARNINGS=0
DEEP_WARNINGS=0   # EXECPLAN2 I-8-2: non-blocking warnings raised only by --deep probes (exit 2)
ok()   { printf '%s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; WARNINGS=$((WARNINGS+1)); }
bad()  { printf '%s✗%s %s\n' "$C_RED" "$C_RESET" "$*"; FAILURES=$((FAILURES+1)); }
# EXECPLAN2 I-8-2: a deep-only soft failure — not blocking (it never gates the
# fast/offline contract), but it bumps the exit code to 2 so CI/automation can
# distinguish "ready, but a costly probe flagged something" from a clean run.
dwarn() { printf '%s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; DEEP_WARNINGS=$((DEEP_WARNINGS+1)); }
sect() { printf '\n%s== %s ==%s\n' "$C_BOLD" "$*" "$C_RESET"; }
have() { command -v "$1" >/dev/null 2>&1; }

# read KEY from .env (first active assignment; empty if absent)
# EXECPLAN2 F-11-2: mirror python-dotenv — strip surrounding quotes, a space-prefixed
# inline comment ( # ...), and surrounding whitespace; keep `sk-abc#notcomment` intact.
envval() {
  [ -f "$ROOT_DIR/.env" ] || { echo ""; return; }
  grep -E "^[[:space:]]*$1=" "$ROOT_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '"' \
    | sed -E 's/[[:space:]]+#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//' || true
}

sect "Tooling"
if have node; then
  NODE_VER="$(node -v 2>/dev/null | sed 's/^v//')"
  NODE_MAJOR="${NODE_VER%%.*}"; NODE_MINOR="$(printf '%s' "$NODE_VER" | cut -d. -f2)"
  if [ "$NODE_MAJOR" -ge 22 ] 2>/dev/null || { [ "$NODE_MAJOR" -eq 20 ] && [ "${NODE_MINOR:-0}" -ge 19 ]; } || [ "$NODE_MAJOR" -eq 21 ]; then
    ok "node $NODE_VER"
  else
    bad "node $NODE_VER — the frontend (vite 7) needs >=20.19. https://nodejs.org/"
  fi
else
  bad "node not found (>=20.19 required)"
fi
have uv  && ok "uv $(uv --version 2>/dev/null | awk '{print $2}')" || bad "uv not found — curl -LsSf https://astral.sh/uv/install.sh | sh"
have git && ok "git $(git --version 2>/dev/null | awk '{print $3}')" || warn "git not found (needed to auto-download deer-flow)"

sect "Backend venv (MiroFish)"
BE_PY="$ROOT_DIR/backend/.venv/bin/python"
if [ -x "$BE_PY" ]; then
  BE_VER="$("$BE_PY" --version 2>/dev/null | awk '{print $2}')"
  case "$BE_VER" in
    3.12.*) ok "backend/.venv on Python $BE_VER" ;;
    3.11.*) warn "backend/.venv on Python $BE_VER — the local graph backend (falkordblite/redis) needs 3.12+; rebuild: ( cd backend && uv sync --python 3.12 )" ;;
    "") bad "backend/.venv python is broken — rebuild: ( cd backend && uv sync --python 3.12 )" ;;
    *) warn "backend/.venv on Python $BE_VER — the simulation stack targets 3.12; if imports below fail, rebuild: ( cd backend && uv sync --python 3.12 )" ;;
  esac
  if "$BE_PY" -c "import camel, oasis, graphiti_core, flask" >/dev/null 2>&1; then
    ok "backend imports OK (camel / oasis / graphiti_core / flask)"
  else
    bad "backend deps missing — run: ( cd backend && uv sync --python 3.12 )"
  fi
  # EXECPLAN2 I-8-5: .env.example <-> Config drift (undocumented knobs hurt discoverability)
  if [ -f "$ROOT_DIR/backend/scripts/check_env_drift.py" ]; then
    if "$BE_PY" "$ROOT_DIR/backend/scripts/check_env_drift.py" --strict >/dev/null 2>&1; then
      ok ".env.example documents every Config env var (no drift)"
    else
      warn ".env.example drift — run: ( cd backend && uv run python scripts/check_env_drift.py )"
    fi
    # ENV-1: advisory pin-divergence audit. Runtime .env pins can silently
    # override improved Config defaults (live example: REPORT_SECTION_CONCURRENCY=1
    # vs default 6 serialises report synthesis). `--pins --strict` exits 1 only
    # when a performance-critical pin diverges — surfaced as a non-blocking warn
    # (never a ✗), preserving doctor's offline/free/advisory contract.
    if [ -f "$ROOT_DIR/.env" ]; then
      if "$BE_PY" "$ROOT_DIR/backend/scripts/check_env_drift.py" --pins --strict >/dev/null 2>&1; then
        ok ".env pins align with current Config defaults (no perf-critical drift)"
      else
        warn ".env pins override improved defaults — audit: ( cd backend && uv run python scripts/check_env_drift.py --pins )"
      fi
    fi
  fi
else
  bad "backend venv missing — run: ( cd backend && uv sync --python 3.12 )  (or ./setup.sh)"
fi

sect "DeerFlow research engine"
DEERFLOW_DIR="${DEERFLOW_DIR:-$(envval DEERFLOW_DIR)}"
DEERFLOW_DIR="${DEERFLOW_DIR:-$ROOT_DIR/deer-flow}"
if [ -d "$DEERFLOW_DIR/backend" ]; then
  ok "deer-flow checkout: $DEERFLOW_DIR"
  [ -f "$DEERFLOW_DIR/deerflow_research.py" ] && ok "bridge entry point installed (deerflow_research.py)" \
    || bad "bridge overlay missing — re-run ./setup.sh (installs deerflow_research.py + patches)"
  [ -f "$DEERFLOW_DIR/config.yaml" ] && ok "deer-flow config.yaml present" \
    || bad "deer-flow/config.yaml missing — re-run ./setup.sh"
  DF_PY="${DEERFLOW_PYTHON:-$(envval DEERFLOW_PYTHON)}"
  DF_PY="${DF_PY:-$DEERFLOW_DIR/backend/.venv/bin/python}"
  if [ -x "$DF_PY" ]; then
    DF_VER="$("$DF_PY" --version 2>/dev/null | awk '{print $2}')"
    if "$DF_PY" -c "import deerflow, langgraph" >/dev/null 2>&1; then
      ok "deer-flow venv OK (Python $DF_VER, deerflow importable)"
    else
      bad "deer-flow venv incomplete — UV_PROJECT_ENVIRONMENT=\"$DEERFLOW_DIR/backend/.venv\" uv sync --project \"$DEERFLOW_DIR/backend\" --python 3.12"
    fi
  else
    bad "deer-flow venv missing ($DF_PY) — re-run ./setup.sh"
  fi
else
  bad "deer-flow not found at $DEERFLOW_DIR — run ./setup.sh (auto-clones it) or set DEERFLOW_DIR"
fi

# Official-data MCP servers (datamcps/: FRED, BLS, BIS, IMF, World Bank Data360,
# US Gov Open Data). Optional by design — an unbuilt or keyless server only drops
# that source from research, it never fails a run — so problems here are
# warnings, never blocking. Only key NAMES are reported, never their values.
sect "Data-source MCP servers"
# cfgval KEY -> an exported KEY wins, else the repo .env (same precedence as
# DEERFLOW_DIR / DEERFLOW_PYTHON above and scripts/setup_datamcps.sh).
cfgval() {
  local value="${!1:-}"
  [ -n "$value" ] || value="$(envval "$1")"
  printf '%s\n' "$value"
}
DS_ENABLED="$(cfgval DATA_SOURCES_ENABLED | tr '[:upper:]' '[:lower:]')"
DS_ENABLED="${DS_ENABLED:-true}"
if [ "$DS_ENABLED" != "true" ]; then
  ok "official data sources disabled (DATA_SOURCES_ENABLED=$DS_ENABLED) — nothing to check"
else
  DS_DIR="$(cfgval DATA_SOURCES_DIR)"; DS_DIR="${DS_DIR:-$ROOT_DIR/datamcps}"
  case "$DS_DIR" in /*) ;; *) DS_DIR="$ROOT_DIR/$DS_DIR" ;; esac
  DS_ALLOW="$(cfgval DATA_SOURCES | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  DS_ALLOW="${DS_ALLOW:-fred,bls,bis,imf,wb,usgov}"

  # node: same resolution as the runtime and scripts/setup_datamcps.sh.
  DS_NODE_SETTING="$(cfgval DATA_SOURCES_NODE)"
  DS_NODE=""
  if [ -n "$DS_NODE_SETTING" ]; then
    if [ -x "$DS_NODE_SETTING" ] && [ ! -d "$DS_NODE_SETTING" ]; then
      DS_NODE="$DS_NODE_SETTING"
    else
      warn "DATA_SOURCES_NODE=$DS_NODE_SETTING is not an executable file — the node-based data servers will be unavailable"
    fi
  else
    for _cand in "$(command -v node 2>/dev/null || true)" \
                 "$HOME/.local/bin/node" /opt/homebrew/bin/node /usr/local/bin/node; do
      if [ -n "$_cand" ] && [ -x "$_cand" ] && [ ! -d "$_cand" ]; then DS_NODE="$_cand"; break; fi
    done
    [ -n "$DS_NODE" ] || warn "node not found for the data servers (fred/bls/bis/usgov) — install Node.js >= 22 or set DATA_SOURCES_NODE"
  fi
  DS_NODE_MAJOR=0
  if [ -n "$DS_NODE" ]; then
    DS_NODE_VER="$("$DS_NODE" -v 2>/dev/null | sed 's/^v//')"
    DS_NODE_MAJOR="${DS_NODE_VER%%.*}"
    case "$DS_NODE_MAJOR" in ''|*[!0-9]*) DS_NODE_MAJOR=0 ;; esac
    if [ "$DS_NODE_MAJOR" -ge 22 ]; then
      ok "data-server node $DS_NODE_VER ($DS_NODE)"
    elif [ "$DS_NODE_MAJOR" -ge 18 ]; then
      warn "data-server node $DS_NODE_VER ($DS_NODE) — usgov needs >= 22 (set DATA_SOURCES_NODE to a newer node)"
    else
      warn "data-server node ${DS_NODE_VER:-unknown} ($DS_NODE) is too old (fred/bls/bis need >= 18, usgov >= 22)"
    fi
  fi

  if [ ! -d "$DS_DIR" ]; then
    warn "datamcps not found at $DS_DIR — set DATA_SOURCES_DIR (research runs without official data)"
  else
    DS_MISSING=""
    # name | runtime entry relative to the servers root (what data_mcp launches)
    for _row in "fred|fred-mcp-server-main/build/index.js" \
                "bls|bls_mcp-main/dist/index.js" \
                "bis|mcp-bis-main/node_modules/tsx/package.json" \
                "imf|imf-data-mcp-main/.venv/bin/imf-data-mcp" \
                "wb|data360-mcp-dev/.venv/bin/python" \
                "usgov|us-gov-open-data-mcp-main/dist/server.js"; do
      _name="${_row%%|*}"; _entry="${_row#*|}"
      case ",$DS_ALLOW," in
        *",$_name,"*) ;;
        *) ok "$_name: disabled by DATA_SOURCES"; continue ;;
      esac
      if [ ! -e "$DS_DIR/$_entry" ]; then
        DS_MISSING="$DS_MISSING $_name"
      elif [ "$_name" = "usgov" ] && [ "$DS_NODE_MAJOR" -lt 22 ]; then
        warn "usgov: built, but unavailable until node >= 22 is configured"
      else
        ok "$_name: built ($_entry)"
      fi
    done
    [ -z "$DS_MISSING" ] || warn "not built:${DS_MISSING} — run: npm run setup:datamcps"
  fi

  DS_KEYS_SET=""; DS_KEYS_UNSET=""
  for _key in FRED_API_KEY BLS_API_KEY EIA_API_KEY BEA_API_KEY CENSUS_API_KEY DATA_GOV_API_KEY SEC_CONTACT_EMAIL; do
    if [ -n "$(cfgval "$_key")" ]; then DS_KEYS_SET="$DS_KEYS_SET $_key"
    else DS_KEYS_UNSET="$DS_KEYS_UNSET $_key"; fi
  done
  ok "data-source keys set:${DS_KEYS_SET:- none}${DS_KEYS_UNSET:+ (optional, not set:$DS_KEYS_UNSET)}"
fi

sect "Configuration (.env)"
if [ -f "$ROOT_DIR/.env" ]; then
  ok ".env exists"
else
  bad ".env missing — cp .env.example .env (or run ./setup.sh)"
fi

# Knowledge graph runs locally (Graphiti). No API key needed; just verify a local
# backend is importable (embedded FalkorDB via falkordblite, or kuzu).
GRAPH_BACKEND="$(envval GRAPH_BACKEND)"; GRAPH_BACKEND="${GRAPH_BACKEND:-auto}"
if [ -n "${BE_PY:-}" ] && [ -x "$BE_PY" ]; then
  if "$BE_PY" -c "import importlib.util,sys; sys.exit(0 if (importlib.util.find_spec('redislite.async_falkordb_client') or importlib.util.find_spec('kuzu')) else 1)" >/dev/null 2>&1; then
    ok "local knowledge graph backend available (GRAPH_BACKEND=$GRAPH_BACKEND, no API key needed)"
  else
    bad "no local graph backend installed — run: ( cd backend && uv sync --python 3.12 )  (installs falkordblite)"
  fi
fi

PROVIDER="$(envval LLM_PROVIDER)"; PROVIDER="${PROVIDER:-claude-cli}"
case "$PROVIDER" in
  claude-cli)
    if have claude; then ok "LLM_PROVIDER=claude-cli and \`claude\` CLI found"
    else bad "LLM_PROVIDER=claude-cli but \`claude\` CLI not on PATH — install Claude Code or switch provider"; fi ;;
  codex-cli)
    if have codex; then ok "LLM_PROVIDER=codex-cli and \`codex\` CLI found"
    else bad "LLM_PROVIDER=codex-cli but \`codex\` CLI not on PATH"; fi ;;
  openai|kimi|minimax|deepseek|qwen|glm)
    KEY="$(envval LLM_API_KEY)"
    case "$KEY" in
      ""|your_api_key|your_api_key_here) bad "LLM_PROVIDER=$PROVIDER needs LLM_API_KEY in .env" ;;
      *) ok "LLM_PROVIDER=$PROVIDER with LLM_API_KEY set" ;;
    esac ;;
  *) warn "Unknown LLM_PROVIDER '$PROVIDER' (expected claude-cli/codex-cli/openai/kimi/minimax/deepseek/qwen/glm)" ;;
esac

DF_MODEL="$(envval DEERFLOW_MODEL)"; DF_MODEL="${DF_MODEL:-claude}"
df_key_check() { # $1 model  $2 env var
  if [ "$DF_MODEL" = "$1" ]; then
    V="$(envval "$2")"
    if [ -n "$V" ]; then ok "DEERFLOW_MODEL=$1 with $2 set"
    else bad "DEERFLOW_MODEL=$1 needs $2 in .env"; fi
  fi
}
case "$DF_MODEL" in
  claude)
    if [ -f "$HOME/.claude/.credentials.json" ] || have claude; then
      ok "DEERFLOW_MODEL=claude (Claude Code OAuth credentials available)"
    else
      bad "DEERFLOW_MODEL=claude needs a Claude Code login — install the \`claude\` CLI and sign in once"
    fi ;;
  codex)
    if [ -f "$HOME/.codex/auth.json" ] || have codex; then ok "DEERFLOW_MODEL=codex (Codex credentials available)"
    else bad "DEERFLOW_MODEL=codex needs \`codex\` login (~/.codex/auth.json)"; fi ;;
  minimax)  df_key_check minimax  MINIMAX_API_KEY ;;
  deepseek) df_key_check deepseek DEEPSEEK_API_KEY ;;
  qwen)     df_key_check qwen     DASHSCOPE_API_KEY ;;
  glm)      df_key_check glm      ZHIPUAI_API_KEY ;;
  kimi)     df_key_check kimi     KIMI_API_KEY ;;
  *) warn "Unknown DEERFLOW_MODEL '$DF_MODEL' (expected claude/minimax/deepseek/qwen/glm/codex/kimi)" ;;
esac

# ===========================================================================
# EXECPLAN2 I-8-2: opt-in deep probes (live credentials + first-run assets + disk)
# ---------------------------------------------------------------------------
# Strictly gated behind --deep so the default contract (offline / free / instant)
# is unchanged. These are the bounded-but-expensive checks the fast path skips:
# a live 1-token completion, embedding-model cache presence, and free disk.
#
# Prefer the richer backend helper (backend/scripts/preflight.py --deep --json)
# when it is present — that is the canonical implementation that reuses the
# settings.py connectivity helpers; doctor only renders its result. When that
# script is absent (its cross-file part is not yet landed), fall back to a
# self-contained inline probe so `doctor --deep` works standalone today.
# ===========================================================================
if [ "$DEEP" -eq 1 ]; then
  sect "Deep probes (--deep: live credentials · embed-model cache · disk)"
  if [ -z "${BE_PY:-}" ] || [ ! -x "$BE_PY" ]; then
    dwarn "skipped — backend venv missing; run: ( cd backend && uv sync --python 3.12 )"
  else
    PREFLIGHT_PY="$ROOT_DIR/backend/scripts/preflight.py"
    DEEP_LINES=0
    # render_deep_lines: read `level<TAB>message` lines on fd-driven input and
    # route each through the matching reporter. Runs in the *current* shell (via
    # process substitution, not a pipe) so FAILURES / DEEP_WARNINGS persist.
    render_deep_lines() {
      while IFS=$'\t' read -r LVL MSG; do
        [ -z "$LVL" ] && continue
        DEEP_LINES=$((DEEP_LINES+1))
        case "$LVL" in
          ok)   ok   "$MSG" ;;
          bad)  bad  "$MSG" ;;
          *)    dwarn "$MSG" ;;   # warn / unknown -> non-blocking deep warning
        esac
      done
    }
    # JSON->TSV normaliser as a single -c program (kept on its own line so the
    # piped stdin is the data, not the script — `python - <<EOF` would shadow it).
    DEEP_JSON_TO_TSV='import json,sys
for ln in sys.stdin:
    ln=ln.strip()
    if not ln: continue
    try: o=json.loads(ln)
    except Exception: continue
    m=str(o.get("message","")).replace("\t"," ").replace("\n"," ")
    print(str(o.get("level","warn"))+"\t"+m)'
    if [ -f "$PREFLIGHT_PY" ]; then
      # Canonical path: delegate to the backend preflight (it owns the
      # connectivity.py reuse). It emits one JSON object per check on stdout
      # ({"level":...,"message":...}); capture it first, then a tiny python pass
      # normalises that to the level<TAB>message protocol render_deep_lines reads.
      # A crash leaves DEEP_OUT empty -> DEEP_LINES stays 0 -> safety net fires.
      DEEP_ARGS=(--deep --json)
      [ "$PULL" -eq 1 ] && DEEP_ARGS+=(--pull)
      DEEP_OUT="$("$BE_PY" "$PREFLIGHT_PY" "${DEEP_ARGS[@]}" 2>/dev/null)"
      render_deep_lines < <(printf '%s\n' "$DEEP_OUT" | "$BE_PY" -c "$DEEP_JSON_TO_TSV")
    else
      # ------------------------------------------------------------------
      # Self-contained inline fallback (used when backend/scripts/preflight.py
      # is absent — its cross-file part is not yet landed). Runs entirely in the
      # backend venv, reads the live Config so every default (base_url / model /
      # data dir / embed model) matches what the pipeline will actually use, and
      # emits the same level<TAB>message protocol.
      # ------------------------------------------------------------------
      render_deep_lines < <(
        DOCTOR_DEEP_PULL="$PULL" DOCTOR_BACKEND_DIR="$ROOT_DIR/backend" "$BE_PY" - <<'PY'
# EXECPLAN2 I-8-2: inline deep probe (used when backend/scripts/preflight.py is
# absent). Bounded, opt-in, network-touching — never runs without --deep.
import os, sys, time, shutil

def emit(level, message):
    # level<TAB>message protocol consumed by render_deep_lines() in doctor.sh.
    msg = str(message).replace("\t", " ").replace("\n", " ")
    print(f"{level}\t{msg}")
    sys.stdout.flush()

# Make `app` importable. doctor.sh passes the backend dir explicitly via
# DOCTOR_BACKEND_DIR (this code is fed on stdin, so __file__ is unreliable).
_backend = os.environ.get("DOCTOR_BACKEND_DIR", "")
for cand in (_backend, os.path.join(os.getcwd(), "backend"), os.getcwd()):
    if cand and os.path.isdir(os.path.join(cand, "app")):
        sys.path.insert(0, cand)
        break

try:
    from app.config import Config  # type: ignore
except Exception as exc:  # pragma: no cover - defensive
    emit("warn", f"deep probe skipped — cannot import Config ({type(exc).__name__})")
    sys.exit(0)

PULL = os.environ.get("DOCTOR_DEEP_PULL") == "1"
warnings = 0
failures = 0

# --- (1) Live LLM completion against the configured provider -----------------
def probe_openai_compat(label, provider, api_key, base_url, model):
    global failures
    if not api_key:
        emit("bad", f"{label}: no API key set — cannot live-test {provider}")
        failures += 1
        return
    # Reuse the same SSRF guard the settings API uses before any network call.
    try:
        from app.utils.security import validate_safe_url
        validate_safe_url(base_url, block_private=getattr(Config, "APP_BLOCK_PRIVATE_URLS", True))
    except Exception as exc:
        emit("bad", f"{label}: refused base_url ({exc})")
        failures += 1
        return
    try:
        from openai import OpenAI
    except Exception:
        emit("warn", f"{label}: openai SDK unavailable — skipped live test")
        return
    client_kwargs = {"api_key": api_key, "base_url": base_url, "timeout": 25, "max_retries": 0}
    if provider == "kimi":
        client_kwargs["default_headers"] = {"User-Agent": getattr(Config, "LLM_USER_AGENT", "claude-cli/1.0.0")}
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    extra = getattr(Config, "_DISABLE_THINKING_EXTRA_BODY", {}).get(provider)
    if extra:
        kwargs["extra_body"] = extra
    started = time.monotonic()
    try:
        OpenAI(**client_kwargs).chat.completions.create(**kwargs)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        hints = {
            401: "invalid or expired API key",
            403: "key valid but access denied (plan/permissions)",
            404: "endpoint or model not found — check Base URL / model name",
            429: "rate limited — key works but quota exhausted",
        }
        hint = hints.get(status) if isinstance(status, int) else None
        emit("bad", f"{label}: live test failed ({hint or 'check key / Base URL / model'})")
        failures += 1
        return
    latency = int((time.monotonic() - started) * 1000)
    emit("ok", f"{label}: live completion OK ({model} · {latency}ms)")

def probe_cli(label, cli):
    global failures
    if shutil.which(cli):
        emit("ok", f"{label}: '{cli}' CLI on PATH (live OAuth/login used at run time)")
    else:
        emit("bad", f"{label}: '{cli}' CLI not on PATH")
        failures += 1

# LLM_PROVIDER probe
provider = (getattr(Config, "LLM_PROVIDER", "") or "").strip().lower()
meta = getattr(Config, "PROVIDER_META", {}).get(provider, {}) or {}
if not meta:
    emit("warn", f"LLM_PROVIDER: unknown provider '{provider}' — skipped live test")
elif not meta.get("openai_compat"):
    probe_cli(f"LLM_PROVIDER={provider}", "claude" if provider == "claude-cli" else "codex")
else:
    base = getattr(Config, "LLM_BASE_URL", None) or meta.get("default_base") or "https://api.openai.com/v1"
    model = getattr(Config, "LLM_MODEL_NAME", None) or meta.get("default_model") or "gpt-4o-mini"
    probe_openai_compat(f"LLM_PROVIDER={provider}", provider, getattr(Config, "LLM_API_KEY", None), base, model)

# DEERFLOW_MODEL credential probe. The DeerFlow model names (minimax/deepseek/
# qwen/glm/kimi) map 1:1 to PROVIDER_META keys, so reuse its default_base /
# default_model / key_env instead of hardcoding URLs (DRY + always in sync).
df_model = (getattr(Config, "DEERFLOW_MODEL", "") or "claude").strip().lower()
_KEY_ENV_FALLBACK = {
    "minimax": "MINIMAX_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY", "glm": "ZHIPUAI_API_KEY", "kimi": "KIMI_API_KEY",
}
_all_meta = getattr(Config, "PROVIDER_META", {}) or {}
if df_model in ("claude", "codex"):
    probe_cli(f"DEERFLOW_MODEL={df_model}", "claude" if df_model == "claude" else "codex")
elif df_model in _all_meta or df_model in _KEY_ENV_FALLBACK:
    dmeta = _all_meta.get(df_model, {})
    key_env = dmeta.get("key_env") or _KEY_ENV_FALLBACK.get(df_model, f"{df_model.upper()}_API_KEY")
    key = os.environ.get(key_env) or ""
    base = os.environ.get(f"{df_model.upper()}_BASE_URL") or dmeta.get("default_base") or "https://api.openai.com/v1"
    model = os.environ.get(f"{df_model.upper()}_MODEL") or dmeta.get("default_model") or df_model
    if not key:
        emit("bad", f"DEERFLOW_MODEL={df_model}: {key_env} not set — research stage will fail")
        failures += 1
    else:
        probe_openai_compat(f"DEERFLOW_MODEL={df_model}", df_model, key, base, model)
else:
    emit("warn", f"DEERFLOW_MODEL: unknown model '{df_model}' — skipped live test")

# --- (2) Embedding model presence in the HF cache ----------------------------
embed = getattr(Config, "GRAPHITI_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
def embed_cached(name):
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return None  # cannot determine (huggingface_hub unavailable)
    # A bare sentence-transformers name resolves under sentence-transformers/<name>.
    repos = [name] if "/" in name else [name, f"sentence-transformers/{name}"]
    markers = ("modules.json", "config_sentence_transformers.json", "config.json")
    for repo in repos:
        for fn in markers:
            try:
                r = try_to_load_from_cache(repo_id=repo, filename=fn)
            except Exception:
                r = None
            # try_to_load_from_cache returns a str path when the file is cached;
            # None when absent, or a sentinel object when HF cached a "no-exist".
            # Only a non-empty str means genuinely present.
            if isinstance(r, str) and r:
                return True
    return False

cached = embed_cached(embed)
if cached is True:
    emit("ok", f"embedding model cached: {embed}")
elif cached is None:
    emit("warn", f"embedding model: cannot inspect HF cache for {embed} (huggingface_hub missing?)")
    warnings += 1
else:
    if PULL:
        emit("warn", f"embedding model {embed} not cached — pre-pulling (~470MB, one-time)…")
        try:
            from sentence_transformers import SentenceTransformer
            SentenceTransformer(embed)  # downloads + caches; raises if offline/unreachable
            if embed_cached(embed):
                emit("ok", f"embedding model pulled and cached: {embed}")
            else:
                emit("warn", f"embedding model {embed} pull finished but cache check still negative")
                warnings += 1
        except Exception as exc:
            emit("bad", f"embedding model {embed} pull failed ({type(exc).__name__}) — need network + ~470MB free")
            failures += 1
    else:
        emit("warn", f"embedding model {embed} not in HF cache — first graph build downloads ~470MB; "
                     f"pre-pull now with: bash scripts/doctor.sh --deep --pull")
        warnings += 1

# --- (3) Free disk against the graph data dir / uploads ----------------------
def gb(n):
    return f"{n / (1024**3):.1f}GB"
checked_paths = set()
for label, path in (("GRAPHITI_DATA_DIR", getattr(Config, "GRAPHITI_DATA_DIR", None)),
                    ("uploads", getattr(Config, "UPLOAD_FOLDER", None))):
    if not path:
        continue
    # disk_usage needs an existing dir; walk up to the nearest existing parent.
    probe = os.path.abspath(path)
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if not probe or not os.path.isdir(probe) or probe in checked_paths:
        continue
    checked_paths.add(probe)
    try:
        free = shutil.disk_usage(probe).free
    except Exception as exc:
        emit("warn", f"{label}: cannot stat free disk for {path} ({type(exc).__name__})")
        warnings += 1
        continue
    # 2GB headroom covers a ~470MB embed model + graph db growth + report artifacts.
    if free < 2 * 1024**3:
        emit("bad", f"{label}: only {gb(free)} free at {probe} — need >=2GB for embed model + graph db")
        failures += 1
    elif free < 5 * 1024**3:
        emit("warn", f"{label}: {gb(free)} free at {probe} — tight; >=5GB recommended for headroom")
        warnings += 1
    else:
        emit("ok", f"{label}: {gb(free)} free at {probe}")

# Exit 1 if a deep probe found a blocking issue, 2 if only warnings, else 0.
sys.exit(1 if failures else (2 if warnings else 0))
PY
      )
    fi
    # render_deep_lines already routed every line through ok/bad/dwarn, so
    # FAILURES / DEEP_WARNINGS are authoritative. The only failure mode left is a
    # child that crashed before emitting anything — surface that as a blocking
    # problem so a broken deep probe never masquerades as "all clear".
    if [ "$DEEP_LINES" -eq 0 ]; then
      bad "deep probes produced no output — the backend Python child likely crashed; re-run: $BE_PY $PREFLIGHT_PY --deep --json"
    fi

    # I4: live official-data probe — the same probe_data_sources() that serves
    # POST /api/settings/data-sources/test. Per enabled provider: MCP initialize +
    # list_tools, then one cache-first catalog sample (BLS: handshake only). Advisory
    # by contract (an unavailable source never fails a run), so problems are deep
    # warnings (exit 2), never ✗. The app logger writes to stdout, so the probe
    # prints its level<TAB>message lines on the original stdout and parks
    # sys.stdout on stderr (discarded here) before importing the backend.
    if [ "${DS_ENABLED:-true}" = "true" ]; then
      DOCTOR_DATA_PROBE='import os, sys
out = sys.stdout
sys.stdout = sys.stderr
def emit(level, message):
    out.write(level + "\t" + " ".join(str(message).split()) + "\n")
    out.flush()
sys.path.insert(0, os.environ["DOCTOR_BACKEND_DIR"])
try:
    from app.api.settings import probe_data_sources
    result = probe_data_sources()
except Exception as exc:
    emit("warn", "official-data probe unavailable (" + type(exc).__name__ + ")")
    raise SystemExit(0)
for name, row in result["providers"].items():
    keys = ", ".join(key + " " + status for key, status in row["keys"].items())
    emit("ok" if row["state"] in ("ok", "disabled") else "warn",
         "data " + name + ": " + row["state"] + " (" + str(row["latency_s"]) + "s) — " + row["detail"]
         + (" [" + keys + "]" if keys else ""))'
      DATA_LINES_BEFORE=$DEEP_LINES
      render_deep_lines < <(DOCTOR_BACKEND_DIR="$ROOT_DIR/backend" "$BE_PY" -c "$DOCTOR_DATA_PROBE" 2>/dev/null)
      if [ "$DEEP_LINES" -eq "$DATA_LINES_BEFORE" ]; then
        dwarn "official-data probe produced no output — the backend Python child likely crashed (advisory; runs continue without official data)"
      fi
    else
      ok "official-data probe skipped (DATA_SOURCES_ENABLED=${DS_ENABLED:-})"
    fi
  fi
fi

printf '\n'
if [ "$FAILURES" -gt 0 ]; then
  bad "$FAILURES blocking problem(s) found (and $((WARNINGS+DEEP_WARNINGS)) warning(s)). Fix the ✗ items above, then re-run: npm run doctor"
  exit 1
elif [ "$DEEP_WARNINGS" -gt 0 ]; then
  total_warn=$((WARNINGS+DEEP_WARNINGS))
  warn "Ready, but $DEEP_WARNINGS deep-probe warning(s) (total $total_warn) — see ⚠ above. Start: ${C_BOLD}npm run dev${C_RESET} → http://localhost:3000/research"
  exit 2
else
  ok "All checks passed${WARNINGS:+ ($WARNINGS warning(s))} — start with: ${C_BOLD}npm run dev${C_RESET} → http://localhost:3000/research"
  exit 0
fi
