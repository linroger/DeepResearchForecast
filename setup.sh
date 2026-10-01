#!/usr/bin/env bash
#
# setup.sh — DeepAgentForecast quick-start / installer
# ---------------------------------------------------------------------------
# Idempotent, re-runnable setup for the "one prompt -> forecast" engine.
#
#   * Checks prerequisites (node>=18, npm, uv, python3) and WARNS (never
#     hard-fails) when something optional is missing.
#   * INTERACTIVE provider picker (TTY runs): choose between the local Claude /
#     Codex CLIs (no API key) and six API-key providers (OpenAI-compatible /
#     Kimi / MiniMax / DeepSeek / Qwen / GLM); API-key providers prompt for the
#     key (silent input) and live-test it with a 1-token completion.
#     Non-interactive runs (CI, piped) silently auto-detect:
#       - `claude` CLI on PATH -> LLM_PROVIDER=claude-cli, DEERFLOW_MODEL=claude
#       - `codex`  CLI on PATH -> LLM_PROVIDER=codex-cli,  DEERFLOW_MODEL=codex
#       - neither               -> default claude-cli + a warning
#   * Scaffolds .env from .env.example (never overwrites an existing .env) and
#     upserts the chosen provider lines safely (re-runs default to your current
#     .env provider, so pressing Enter never clobbers an existing config).
#   * Installs root + frontend + backend dependencies.
#   * ASSEMBLES the DeerFlow 2.0 engine into ./deer-flow inside this repo
#     (gitignored): seeds from the vendored ./deer-flow-2.0.0 build when
#     present, else falls back to a pinned upstream clone; then applies the bridge
#     overlay (research driver, patched model providers, loop-detection middleware,
#     deep-research skill, and a ready-to-use config.yaml with claude / minimax /
#     deepseek / qwen / glm / codex / kimi stanzas) and builds its isolated
#     Python 3.12 venv.
#
# Safe to run multiple times. Optional steps are guarded so a missing piece
# (e.g. no vendored build AND no network for the clone fallback) never aborts the
# whole script.
# ---------------------------------------------------------------------------

# Fail fast on errors, unset variables, and broken pipes — but we deliberately
# guard every OPTIONAL step with `|| true` / explicit `if` blocks so an absent
# optional dependency does not abort the run.
set -euo pipefail

# ---------------------------------------------------------------------------
# Paths & pretty-printing helpers
# ---------------------------------------------------------------------------

# Resolve the directory this script lives in so the script works no matter the
# caller's current working directory. ROOT_DIR is the MiroFish project root.
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"

# Colour output only when stdout is an interactive terminal.
if [ -t 1 ]; then
  C_RESET="$(printf '\033[0m')"
  C_BOLD="$(printf '\033[1m')"
  C_GREEN="$(printf '\033[32m')"
  C_YELLOW="$(printf '\033[33m')"
  C_CYAN="$(printf '\033[36m')"
else
  C_RESET="" C_BOLD="" C_GREEN="" C_YELLOW="" C_CYAN=""
fi

# Status markers: ✓ for success, ⚠ for warnings, › for info/steps.
ok()    { printf '%s✓%s %s\n'  "$C_GREEN"  "$C_RESET" "$*"; }
warn()  { printf '%s⚠%s %s\n'  "$C_YELLOW" "$C_RESET" "$*"; }
info()  { printf '%s›%s %s\n'   "$C_CYAN"   "$C_RESET" "$*"; }
step()  { printf '\n%s== %s ==%s\n' "$C_BOLD" "$*" "$C_RESET"; }

# ---------------------------------------------------------------------------
# 1) Banner
# ---------------------------------------------------------------------------
printf '%s' "$C_BOLD"
cat <<'BANNER'
============================================================
   DeepAgentForecast — setup
   one prompt -> research -> simulate -> forecast
============================================================
BANNER
printf '%s\n' "$C_RESET"
info "Project root: $ROOT_DIR"

# ---------------------------------------------------------------------------
# 2) Prerequisite checks (warn, never hard-fail)
# ---------------------------------------------------------------------------
step "Checking prerequisites"

# have <cmd> -> true if the command is on PATH.
have() { command -v "$1" >/dev/null 2>&1; }

# Track whether anything important is missing so we can summarise at the end.
MISSING_PREREQS=0

# --- node (>= 20.19; vite 7 requires ^20.19 || >=22.12) ---
if have node; then
  # `node -v` prints e.g. "v20.11.0"; strip the leading 'v' and take major/minor.
  NODE_VER="$(node -v 2>/dev/null | sed 's/^v//')"
  NODE_MAJOR="${NODE_VER%%.*}"
  NODE_MINOR="$(printf '%s' "$NODE_VER" | cut -d. -f2)"
  if [ -n "$NODE_MAJOR" ] 2>/dev/null && { [ "$NODE_MAJOR" -ge 22 ] || { [ "$NODE_MAJOR" -eq 20 ] && [ "${NODE_MINOR:-0}" -ge 19 ]; } || [ "$NODE_MAJOR" -eq 21 ]; }; then
    ok "node $NODE_VER (>=20.19)"
  else
    warn "node $NODE_VER found, but the frontend (vite 7) needs >=20.19 (or >=22.12)."
    warn "    Update Node.js: https://nodejs.org/"
    MISSING_PREREQS=1
  fi
else
  warn "node not found (>=20.19 required). Install Node.js: https://nodejs.org/"
  MISSING_PREREQS=1
fi

# --- npm ---
if have npm; then
  ok "npm $(npm -v 2>/dev/null)"
else
  warn "npm not found. It ships with Node.js: https://nodejs.org/"
  MISSING_PREREQS=1
fi

# --- uv (Python package/venv manager) ---
if have uv; then
  ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"
else
  warn "uv not found. Install it (Python package manager) with:"
  warn "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  warn "    docs: https://docs.astral.sh/uv/"
  MISSING_PREREQS=1
fi

# --- python3 ---
if have python3; then
  ok "python3 $(python3 --version 2>/dev/null | awk '{print $2}')"
else
  warn "python3 not found. uv can install/manage Python for you (uv python install)."
  warn "    See https://docs.astral.sh/uv/ for details."
  MISSING_PREREQS=1
fi

# --- git (needed to auto-download the DeerFlow research engine) ---
if have git; then
  ok "git $(git --version 2>/dev/null | awk '{print $3}')"
else
  warn "git not found. It is needed to auto-clone the DeerFlow research engine."
  warn "    Install: https://git-scm.com/downloads"
  MISSING_PREREQS=1
fi

if [ "$MISSING_PREREQS" -ne 0 ]; then
  warn "Some prerequisites are missing/old. Setup will continue, but install the"
  warn "items above before running the app for the full pipeline to work."
fi

# ---------------------------------------------------------------------------
# 3) Choose the model provider (interactive picker; auto-detect fallback)
# ---------------------------------------------------------------------------
step "Choosing model provider"

# Provider tables (bash-3.2-compatible: no associative arrays on stock macOS).
# Fields per provider: label | needs API key | DeerFlow research model |
# default base URL / model name | provider-specific key env mirrored for deer-flow.
PROVIDER_IDS=(claude-cli codex-cli openai kimi minimax deepseek qwen glm)
PROVIDER_LABELS=(
  "Claude Code (local CLI subscription — no API key)"
  "Codex (local CLI / ChatGPT subscription — no API key)"
  "OpenAI-compatible API (needs API key)"
  "Kimi-for-coding (needs API key)"
  "MiniMax code plan (needs API key)"
  "DeepSeek (needs API key)"
  "Qwen / DashScope (needs API key)"
  "GLM / Z.ai (needs API key)"
)
PROVIDER_NEEDS_KEY=(no no yes yes yes yes yes yes)
PROVIDER_DF_MODEL=(claude codex claude kimi minimax deepseek qwen glm)
PROVIDER_BASE=(
  "" ""
  "https://api.openai.com/v1"
  "https://api.kimi.com/coding/v1"
  "https://api.minimaxi.com/v1"
  "https://api.deepseek.com/v1"
  "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
  "https://api.z.ai/api/paas/v4"
)
PROVIDER_MODEL=(
  "" ""
  "gpt-4o-mini"
  "kimi-for-coding"
  "MiniMax-M3"
  "deepseek-chat"
  "qwen-plus"
  "glm-4.6"
)
PROVIDER_KEY_ENV=("" "" "" "KIMI_API_KEY" "MINIMAX_API_KEY" "DEEPSEEK_API_KEY" "DASHSCOPE_API_KEY" "ZHIPUAI_API_KEY")

# Auto-detect a sensible default: a local CLI means zero-config (subscription
# OAuth, no API key). DEERFLOW_MODEL must be one of the models DeerFlow's
# research stage supports (claude | minimax | deepseek | qwen | glm | codex | kimi).
DETECTED_IDX=0   # default: claude-cli
DEFAULT_BADGE="detected default"
if have claude; then
  DETECTED_IDX=0
  ok "Claude Code CLI detected (recommended default — no API key needed)"
elif have codex; then
  DETECTED_IDX=1
  ok "Codex CLI detected (recommended default — no API key needed)"
else
  warn "No 'claude' or 'codex' CLI found on PATH — pick an API-key provider below,"
  warn "or install Claude Code (https://claude.com/claude-code) and re-run."
fi

# Re-runs: a provider already configured in .env beats auto-detection as the
# menu default, so pressing Enter never clobbers an existing configuration.
PRE_ENV_PROVIDER=""
if [ -f "$ROOT_DIR/.env" ]; then
  PRE_ENV_PROVIDER="$(grep -E '^[[:space:]]*LLM_PROVIDER=' "$ROOT_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '[:space:]' || true)"
  if [ -n "$PRE_ENV_PROVIDER" ]; then
    i=0
    for pid in "${PROVIDER_IDS[@]}"; do
      if [ "$pid" = "$PRE_ENV_PROVIDER" ]; then
        DETECTED_IDX="$i"
        DEFAULT_BADGE="current .env setting"
        ok "Existing .env provider found: $PRE_ENV_PROVIDER (menu default)"
        break
      fi
      i=$((i + 1))
    done
  fi
fi

LLM_PROVIDER="${PROVIDER_IDS[$DETECTED_IDX]}"
DEERFLOW_MODEL="${PROVIDER_DF_MODEL[$DETECTED_IDX]}"
CHOSEN_IDX="$DETECTED_IDX"
LLM_API_KEY_INPUT=""
INTERACTIVE_PICKED=0

# Interactive picker — only when stdin is a TTY (CI / piped runs keep the
# auto-detected default silently). SETUP_NONINTERACTIVE=1 also skips it.
if [ -t 0 ] && [ "${SETUP_NONINTERACTIVE:-0}" != "1" ]; then
  INTERACTIVE_PICKED=1
  printf '\n  Select your model provider (how the pipeline calls its LLM):\n\n'
  i=0
  for label in "${PROVIDER_LABELS[@]}"; do
    n=$((i + 1))
    if [ "$i" -eq "$DETECTED_IDX" ]; then
      printf '    %s%d) %s  [%s]%s\n' "$C_GREEN" "$n" "$label" "$DEFAULT_BADGE" "$C_RESET"
    else
      printf '    %d) %s\n' "$n" "$label"
    fi
    i=$((n))
  done
  printf '\n  Choice [1-%d, Enter = %d]: ' "${#PROVIDER_IDS[@]}" "$((DETECTED_IDX + 1))"
  read -r PICK || PICK=""
  case "$PICK" in
    (''|*[!0-9]*) CHOSEN_IDX="$DETECTED_IDX" ;;       # Enter / non-numeric -> default
    (*) if [ "$PICK" -ge 1 ] && [ "$PICK" -le "${#PROVIDER_IDS[@]}" ]; then
          CHOSEN_IDX=$((PICK - 1))
        else
          warn "Out-of-range choice '$PICK' — keeping the default."
          CHOSEN_IDX="$DETECTED_IDX"
        fi ;;
  esac
  LLM_PROVIDER="${PROVIDER_IDS[$CHOSEN_IDX]}"
  DEERFLOW_MODEL="${PROVIDER_DF_MODEL[$CHOSEN_IDX]}"
  ok "Provider: $LLM_PROVIDER (deep-research model: $DEERFLOW_MODEL)"

  # API-key providers: prompt for the key now (silent input, never echoed).
  if [ "${PROVIDER_NEEDS_KEY[$CHOSEN_IDX]}" = "yes" ]; then
    printf '  Paste your %s API key (or press Enter to add it to .env later): ' "$LLM_PROVIDER"
    read -rs LLM_API_KEY_INPUT || LLM_API_KEY_INPUT=""
    printf '\n'
    if [ -n "$LLM_API_KEY_INPUT" ]; then
      ok "API key captured (will be written to .env, never echoed)"
    else
      warn "Skipped — set LLM_API_KEY in .env before running."
    fi
  fi
else
  ok "Non-interactive run -> LLM_PROVIDER=$LLM_PROVIDER (auto-detected default)"
fi

# ---------------------------------------------------------------------------
# 4) Scaffold & configure .env  (NEVER overwrite an existing .env)
# ---------------------------------------------------------------------------
step "Configuring .env"

ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"

if [ -f "$ENV_FILE" ]; then
  ok ".env already exists — leaving it in place (not overwriting)."
elif [ -f "$ENV_EXAMPLE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  ok "Created .env from .env.example"
else
  # Last-resort minimal stub so the upsert below has a file to work on.
  warn ".env.example not found; creating a minimal .env stub."
  cat > "$ENV_FILE" <<'STUB'
LLM_PROVIDER=claude-cli
# Local knowledge graph (no API key needed). auto -> embedded FalkorDB (falkordblite).
GRAPH_BACKEND=auto
STUB
fi

# upsert_env KEY VALUE
# --------------------
# Safely set "KEY=VALUE" in $ENV_FILE:
#   * if an active (non-commented) "KEY=" line exists, replace it in place;
#   * otherwise append the line.
# Uses awk to a temp file (portable across BSD/macOS & GNU sed differences) and
# treats the value as a literal string (no regex/escape surprises).
upsert_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  KEY="$key" VALUE="$value" awk '
    BEGIN { key = ENVIRON["KEY"]; value = ENVIRON["VALUE"]; found = 0 }
    {
      # Match an active assignment line for this key (allow leading spaces),
      # ignoring commented-out (#) lines so we never resurrect a comment.
      if ($0 ~ "^[[:space:]]*" key "=") {
        if (!found) { print key "=" value; found = 1 }
        # drop any duplicate active lines for the same key
        next
      }
      print
    }
    END { if (!found) print key "=" value }
  ' "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"
}

CURRENT_PROVIDER="$(grep -E '^[[:space:]]*LLM_PROVIDER=' "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '[:space:]' || true)"
CURRENT_DF_MODEL="$(grep -E '^[[:space:]]*DEERFLOW_MODEL=' "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '[:space:]' || true)"

if [ "$INTERACTIVE_PICKED" = "1" ]; then
  # The user explicitly chose a provider in the picker — persist that choice.
  # (Pressing Enter selects the current .env provider, so re-runs are no-ops.)
  upsert_env "LLM_PROVIDER" "$LLM_PROVIDER"
  ok "Set LLM_PROVIDER=$LLM_PROVIDER in .env"
  if [ "$LLM_PROVIDER" = "$CURRENT_PROVIDER" ] && [ -n "$CURRENT_DF_MODEL" ]; then
    # Same provider as before: keep any custom DEERFLOW_MODEL the user tuned.
    DEERFLOW_MODEL="$CURRENT_DF_MODEL"
    ok "Keeping existing DEERFLOW_MODEL=$CURRENT_DF_MODEL from .env"
  else
    upsert_env "DEERFLOW_MODEL" "$DEERFLOW_MODEL"
    ok "Set DEERFLOW_MODEL=$DEERFLOW_MODEL in .env"
  fi

  if [ "${PROVIDER_NEEDS_KEY[$CHOSEN_IDX]}" = "yes" ]; then
    # Connection defaults: write base URL / model name when the provider just
    # changed (stale values from another provider would break calls) or when
    # they are missing; otherwise leave the user's tuning alone.
    CURRENT_BASE="$(grep -E '^[[:space:]]*LLM_BASE_URL=' "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '[:space:]' || true)"
    CURRENT_MODEL="$(grep -E '^[[:space:]]*LLM_MODEL_NAME=' "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '[:space:]' || true)"
    if [ "$LLM_PROVIDER" != "$CURRENT_PROVIDER" ] || [ -z "$CURRENT_BASE" ]; then
      upsert_env "LLM_BASE_URL" "${PROVIDER_BASE[$CHOSEN_IDX]}"
      ok "Set LLM_BASE_URL=${PROVIDER_BASE[$CHOSEN_IDX]}"
    fi
    if [ "$LLM_PROVIDER" != "$CURRENT_PROVIDER" ] || [ -z "$CURRENT_MODEL" ]; then
      upsert_env "LLM_MODEL_NAME" "${PROVIDER_MODEL[$CHOSEN_IDX]}"
      ok "Set LLM_MODEL_NAME=${PROVIDER_MODEL[$CHOSEN_IDX]}"
    fi
    if [ -n "$LLM_API_KEY_INPUT" ]; then
      upsert_env "LLM_API_KEY" "$LLM_API_KEY_INPUT"
      # Mirror the key into the provider-specific env var that
      # deer-flow/config.yaml resolves via $VAR for the deep-research stage.
      KEY_ENV="${PROVIDER_KEY_ENV[$CHOSEN_IDX]}"
      if [ -n "$KEY_ENV" ]; then
        upsert_env "$KEY_ENV" "$LLM_API_KEY_INPUT"
      fi
      ok "LLM_API_KEY saved to .env${KEY_ENV:+ (mirrored to $KEY_ENV for deep research)}"
    fi
  fi
else
  # Non-interactive: never clobber a provider the user already configured —
  # only write the auto-detected values when the keys are missing or empty.
  if [ -n "$CURRENT_PROVIDER" ]; then
    LLM_PROVIDER="$CURRENT_PROVIDER"
    ok "Keeping existing LLM_PROVIDER=$CURRENT_PROVIDER from .env (auto-detect skipped)"
  else
    upsert_env "LLM_PROVIDER" "$LLM_PROVIDER"
    ok "Set LLM_PROVIDER=$LLM_PROVIDER in .env"
  fi
  if [ -n "$CURRENT_DF_MODEL" ]; then
    DEERFLOW_MODEL="$CURRENT_DF_MODEL"
    ok "Keeping existing DEERFLOW_MODEL=$CURRENT_DF_MODEL from .env"
  else
    upsert_env "DEERFLOW_MODEL" "$DEERFLOW_MODEL"
    ok "Set DEERFLOW_MODEL=$DEERFLOW_MODEL in .env"
  fi
fi

# --- Optional live key test (only when a fresh key was just entered) ---------
# A single 1-token chat completion against the provider's endpoint: catches
# typo'd keys in setup instead of 40 minutes into a research run. You can also
# re-test any time from the UI Settings menu ("Test connection").
if [ -n "$LLM_API_KEY_INPUT" ] && have curl; then
  info "Testing the API key against ${PROVIDER_BASE[$CHOSEN_IDX]} …"
  UA_HEADER=()
  if [ "$LLM_PROVIDER" = "kimi" ]; then
    # The Kimi-for-coding gateway validates a coding-agent User-Agent.
    UA_HEADER=(-H "User-Agent: claude-cli/1.0.0")
  fi
  # ${arr[@]+...} guards the empty-array expansion (bash 3.2 + set -u safe).
  # Secret hygiene: feed the bearer token via a curl config on stdin
  # (--config -) so it never lands in argv (ps / /proc/<pid>/cmdline); write
  # the response to a mktemp 0600 file instead of a predictable /tmp name.
  SETUP_LLM_TEST_TMP="$(mktemp "${TMPDIR:-/tmp}/setup_llm_test.XXXXXX")"
  chmod 600 "$SETUP_LLM_TEST_TMP" 2>/dev/null || true
  HTTP_CODE="$(curl -sS -o "$SETUP_LLM_TEST_TMP" -w '%{http_code}' --max-time 25 \
    "${PROVIDER_BASE[$CHOSEN_IDX]}/chat/completions" \
    -H "Content-Type: application/json" \
    ${UA_HEADER[@]+"${UA_HEADER[@]}"} \
    --config - \
    -d "{\"model\":\"${PROVIDER_MODEL[$CHOSEN_IDX]}\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":1}" \
    2>/dev/null <<EOF || printf '000'
header = "Authorization: Bearer ${LLM_API_KEY_INPUT}"
EOF
)"
  if [ "$HTTP_CODE" = "200" ]; then
    ok "API key works (HTTP 200 from ${PROVIDER_MODEL[$CHOSEN_IDX]})"
  elif [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "403" ]; then
    warn "API key REJECTED (HTTP $HTTP_CODE). Double-check the key in .env (LLM_API_KEY)."
  elif [ "$HTTP_CODE" = "000" ]; then
    warn "Could not reach the provider endpoint (offline?). Key saved; test later from"
    warn "    the UI Settings menu ('Test connection')."
  else
    warn "Provider returned HTTP $HTTP_CODE — key saved; verify from the UI Settings menu."
  fi
  rm -f "$SETUP_LLM_TEST_TMP" 2>/dev/null || true
  unset SETUP_LLM_TEST_TMP LLM_API_KEY_INPUT
fi

# --- Knowledge graph: local Graphiti (no API key) ---------------------------
# The knowledge graph now runs locally via Graphiti on an embedded FalkorDB
# (falkordblite) — no Zep account, no API key, no external service. The backend
# 'uv sync' step below installs everything; entity/relation extraction reuses your
# configured LLM_PROVIDER and embeddings run locally (sentence-transformers).
info "Knowledge graph: local Graphiti + embedded FalkorDB (no API key required)."

# ---------------------------------------------------------------------------
# 5) Install dependencies
# ---------------------------------------------------------------------------

# --- Root + frontend npm deps ---
# Guarded so an npm failure WARNS but never aborts the run (set -euo pipefail is
# active); the DeerFlow download below must still happen even if npm hiccups.
step "Installing root + frontend dependencies (npm)"
if have npm; then
  npm_failed=0
  # Node deps only here ("setup" = root + frontend). The backend venv is built
  # in the next step with an explicit Python pin — using "setup:all" would run
  # an extra, redundant `uv sync` first.
  if [ -f "$ROOT_DIR/package.json" ] && grep -q '"setup"' "$ROOT_DIR/package.json" 2>/dev/null; then
    ( cd "$ROOT_DIR" && npm run setup ) || npm_failed=1
  else
    ( cd "$ROOT_DIR" && npm install ) || npm_failed=1
    if [ -d "$ROOT_DIR/frontend" ]; then
      ( cd "$ROOT_DIR/frontend" && npm install ) || npm_failed=1
    fi
  fi
  if [ "$npm_failed" -eq 0 ]; then
    ok "Root + frontend npm dependencies installed"
  else
    warn "npm install hit an error (see output above). Setup continues — re-run"
    warn "    'npm run setup' (or 'npm install') in the project root later."
  fi
else
  warn "Skipping npm install — npm is not available."
fi

# --- Backend Python venv via uv ---
# Guarded the same way: a failed uv sync warns and continues.
# PINNED to Python 3.12: the camel-ai/camel-oasis simulation stack targets
# <=3.12 (a 3.13/3.14 default interpreter breaks the build out of the box).
# backend/.python-version carries the same pin for bare `uv sync` / `uv run`.
step "Installing backend dependencies (uv sync, Python 3.12)"
if have uv && [ -d "$ROOT_DIR/backend" ]; then
  if ( cd "$ROOT_DIR/backend" && uv sync --python 3.12 ); then
    ok "Backend venv ready (backend/.venv, Python 3.12)"
  else
    warn "Backend 'uv sync' failed (see output above). Setup continues — retry with:"
    warn "    ( cd \"$ROOT_DIR/backend\" && uv sync --python 3.12 )"
  fi
elif [ ! -d "$ROOT_DIR/backend" ]; then
  warn "backend/ directory not found — skipping backend install."
else
  warn "Skipping backend 'uv sync' — uv is not available (see install hint above)."
fi

# --- DeerFlow research engine (./deer-flow inside this repo) — REQUIRED for
#     the deep research stage (stage 1) of a full run. setup.sh DOWNLOADS it:
#     clone (pinned) -> apply the bridge overlay -> build its isolated venv.
#     The checkout is gitignored, so everything lives in this single folder. ---
step "Setting up DeerFlow research engine (./deer-flow)"

# Where to put deer-flow, and where to get the engine from.
#   * DEERFLOW_DIR        — runtime location (default: ./deer-flow in this repo).
#   * DEERFLOW_VENDOR_DIR — PREFERRED source: a DeerFlow 2.0 build dropped into
#     the repo (default: ./deer-flow-2.0.0). This is the EXACT engine the
#     bridge overlay targets, so the integration is deterministic and offline.
#   * DEERFLOW_REPO / DEERFLOW_REF — FALLBACK only (when the vendor dir is
#     absent): a shallow upstream clone pinned to the commit the bridge overlay's
#     base matches (claude_provider / credential_loader / loop_detection are
#     byte-identical between this pin and the vendored RC outside the patched
#     regions, so the overlay applies cleanly either way). Set DEERFLOW_REF=main
#     to track upstream HEAD instead.
DEERFLOW_DIR="${DEERFLOW_DIR:-$ROOT_DIR/deer-flow}"
DEERFLOW_VENDOR_DIR="${DEERFLOW_VENDOR_DIR:-$ROOT_DIR/deer-flow-2.0.0}"
DEERFLOW_REPO="${DEERFLOW_REPO:-https://github.com/bytedance/deer-flow.git}"
DEERFLOW_REF="${DEERFLOW_REF:-799bef6d9dbc3a2cb37ce8177eeeabe2a33d8971}"
BRIDGE_DIR="$ROOT_DIR/deerflow_bridge"

# 1) Obtain the engine if it isn't already there. A fresh acquisition is only
#    attempted into a missing/empty directory; an existing checkout is kept (the
#    overlay in step 2 is re-applied either way). Two sources, in priority order:
#      (a) PREFERRED — copy the pinned DeerFlow 2.0 build vendored in this repo
#          ($DEERFLOW_VENDOR_DIR). Deterministic, offline, and exactly what the
#          bridge overlay targets.
#      (b) FALLBACK — a SHALLOW upstream clone (--depth 1 + depth-1 fetch of the
#          pinned commit) when no vendor dir is present.
#    Either way the checkout is then TRIMMED to what the headless research bridge
#    actually uses: backend/ (engine + venv), skills/, config.yaml, README/LICENSE
#    for attribution. The web frontend, docs, docker, CI and the .git dir are dead
#    weight here. To update the engine later, delete deer-flow/ (or drop a newer
#    deer-flow-2.0-* vendor dir) and re-run ./setup.sh.
DF_ACQUIRED=0
if [ ! -d "$DEERFLOW_DIR/.git" ] && [ ! -d "$DEERFLOW_DIR/backend" ]; then
  if [ -d "$DEERFLOW_VENDOR_DIR/backend" ]; then
    info "Seeding DeerFlow 2.0 engine from vendored build -> $DEERFLOW_DIR"
    info "    source: $DEERFLOW_VENDOR_DIR"
    if cp -R "$DEERFLOW_VENDOR_DIR" "$DEERFLOW_DIR" 2>/dev/null; then
      ok "Seeded deer-flow from $(basename "$DEERFLOW_VENDOR_DIR")"
      DF_ACQUIRED=1
    else
      warn "Could not copy the vendored DeerFlow build from $DEERFLOW_VENDOR_DIR."
    fi
  elif have git; then
    info "No vendored DeerFlow build at $DEERFLOW_VENDOR_DIR; cloning upstream -> $DEERFLOW_DIR"
    if git clone --quiet --depth 1 "$DEERFLOW_REPO" "$DEERFLOW_DIR"; then
      ok "Cloned deer-flow (shallow) from $DEERFLOW_REPO"
      if [ "$DEERFLOW_REF" != "main" ]; then
        # GitHub allows fetching an arbitrary commit SHA at depth 1.
        if git -C "$DEERFLOW_DIR" fetch --quiet --depth 1 origin "$DEERFLOW_REF" 2>/dev/null \
           && git -C "$DEERFLOW_DIR" checkout --quiet FETCH_HEAD 2>/dev/null; then
          ok "Pinned deer-flow to commit ${DEERFLOW_REF:0:12}"
        else
          warn "Pinned commit ${DEERFLOW_REF:0:12} could not be fetched; staying on the"
          warn "default branch. The bridge overlay still applies, but if the research"
          warn "stage misbehaves, set DEERFLOW_REF=main or report it so we refresh the pin."
        fi
      fi
      DF_ACQUIRED=1
    else
      warn "git clone of deer-flow failed (offline or blocked?)."
      warn "Drop a DeerFlow 2.0 build at $DEERFLOW_VENDOR_DIR, or clone manually:"
      warn "    git clone --depth 1 $DEERFLOW_REPO \"$DEERFLOW_DIR\""
    fi
  else
    warn "No vendored build and git not found — cannot obtain deer-flow."
    warn "Drop a DeerFlow 2.0 build at $DEERFLOW_VENDOR_DIR, or install git and clone:"
    warn "    git clone --depth 1 $DEERFLOW_REPO \"$DEERFLOW_DIR\""
  fi
  if [ "$DF_ACQUIRED" = "1" ] && [ -d "$DEERFLOW_DIR" ]; then
    (
      cd "$DEERFLOW_DIR" && rm -rf .git frontend docs docker contracts scripts \
        .github .agent pr-build logs Makefile Install.md CONTRIBUTING.md \
        CODE_OF_CONDUCT.md SECURITY.md README_fr.md README_ja.md README_ru.md \
        README_zh.md deer-flow.code-workspace config.example.yaml \
        extensions_config.example.json .pre-commit-config.yaml .gitattributes \
        .gitignore .dockerignore .DS_Store
    ) 2>/dev/null || true
    ok "Trimmed deer-flow to runtime essentials (backend/, skills/, config)"
  fi
else
  ok "deer-flow already present at $DEERFLOW_DIR — not re-acquiring."
fi

# 2) Apply the bridge overlay so the research stage matches what this project
#    expects. The overlay is idempotent (plain file copies) and lives in
#    deerflow_bridge/ so the integration is fully reproducible from this repo.
if [ -d "$DEERFLOW_DIR/backend" ] && [ -d "$BRIDGE_DIR" ]; then
  info "Applying DeerFlow bridge overlay from $BRIDGE_DIR"

  # (a) The research driver / bridge entry point (backend invokes this).
  if [ -f "$BRIDGE_DIR/deerflow_research.py" ]; then
    cp "$BRIDGE_DIR/deerflow_research.py" "$DEERFLOW_DIR/deerflow_research.py"
    ok "Installed deerflow_research.py (bridge entry point)"
  fi

  # (a2) Config-reflected tool modules registered in config.yaml as BARE module
  #     names (`use: market_tools:...`, `use: search_tools:...`, `use: cached_fetch:...`).
  #   - research_budget.py is imported by search_tools/cached_fetch and must be
  #     colocated with them for the shared LOOP-007 SQLite control plane.
  #     deerflow_research.py runs as `python <deer-flow>/deerflow_research.py`, so
  #     sys.path[0] is the deer-flow dir and the harness reflection resolver
  #     (resolve_variable -> import_module) imports these by bare name — they MUST
  #     sit next to config.yaml in deer-flow/ or web_search/web_fetch/prediction_market
  #     tools fail to load. Deploy all four so the wiring is reproducible.
  #   - linear_research.py + research_gateway.py (+ evidence_spans.py and
  #     derived_numbers.py, which linear_research imports) are the deep-research engine v3
  #     (RESEARCH_ENGINE=v3, the default). deerflow_research.py imports them by
  #     bare name, so they must be colocated too or the v3 dispatch hits ImportError.
  #   - source_dates.py is the source publication-date parser cached_fetch and
  #     research_gateway import by bare name (RESEARCH_SOURCE_DATES).
  #   - data_tools.py is the official-data vendor module (FRED/ALFRED
  #     vintage-pinned macro series), imported by bare name once the research
  #     engine binds it.
  #     Keep this list in sync with _sync_deerflow_bridge_if_stale in
  #     backend/app/services/pipeline_orchestrator.py (the launch-time drift guard).
  for _tool_mod in market_tools.py search_tools.py cached_fetch.py research_budget.py runtime_skill_sync.py linear_research.py research_gateway.py evidence_spans.py source_dates.py data_tools.py derived_numbers.py; do
    if [ -f "$BRIDGE_DIR/$_tool_mod" ]; then
      cp "$BRIDGE_DIR/$_tool_mod" "$DEERFLOW_DIR/$_tool_mod"
      case "$_tool_mod" in
        runtime_skill_sync.py)
          ok "Installed runtime_skill_sync.py (runtime bundle verifier)" ;;
        linear_research.py|research_gateway.py|evidence_spans.py|derived_numbers.py)
          ok "Installed $_tool_mod (deep-research engine v3)" ;;
        source_dates.py)
          ok "Installed source_dates.py (source publication-date parser)" ;;
        data_tools.py)
          ok "Installed data_tools.py (official-data vendor tools)" ;;
        *)
          ok "Installed $_tool_mod (config-reflected bridge tool)" ;;
      esac
    fi
  done

  # (b) Patched model providers: macOS-Keychain OAuth + OAuth-preference for
  #     claude_provider (fixes the 'claude' 401) and credential_loader. The
  #     patched_minimax.py shipped here is DeerFlow 2.0's own upstreamed
  #     'user name must be consistent' fix carried verbatim, so applying it is a
  #     no-op on the vendored RC engine and back-ports the fix on an older
  #     clone-fallback base — it never downgrades the upstream implementation.
  DF_MODELS="$DEERFLOW_DIR/backend/packages/harness/deerflow/models"
  if [ -d "$BRIDGE_DIR/patches/models" ] && [ -d "$DF_MODELS" ]; then
    cp "$BRIDGE_DIR/patches/models/"*.py "$DF_MODELS/"
    ok "Applied provider patches (claude_provider, credential_loader, patched_minimax)"
  fi

  # (b2) Authoritatively deploy the complete bridge-managed skill set.  setup
  #     and the orchestrator invoke the same deterministic manifest, lock,
  #     staging, verification, atomic-swap, and pruning implementation.
  SKILL_SYNC_HELPER="$BRIDGE_DIR/runtime_skill_sync.py"
  if [ -d "$BRIDGE_DIR/skills" ] && [ -d "$DEERFLOW_DIR/skills" ]; then
    if [ ! -f "$SKILL_SYNC_HELPER" ] || ! have python3; then
      warn "Required authoritative runtime skill sync helper/python3 is unavailable."
      exit 1
    fi
    if _skill_sync_json="$(python3 "$SKILL_SYNC_HELPER" \
      --source-root "$BRIDGE_DIR/skills" \
      --deployed-public-root "$DEERFLOW_DIR/skills/public")"; then
      ok "Authoritative runtime skill bundle deployed and verified"
      info "    $_skill_sync_json"
    else
      warn "Required runtime skill bundle deployment failed; refusing partial setup."
      exit 1
    fi
  fi

  # (b3) Patched middlewares: loop-detection counters reset per agent run;
  #     provider model calls share an application-level cross-process lease,
  #     including lead/subagent and middleware-internal title/summarization calls.
  #     Upstream accumulates per-tool call counts across ALL turns of a thread,
  #     so multi-pass deep research permanently force-stops web_search from
  #     pass 2 onward once the cumulative count crosses the safety limit.
  DF_MIDDLEWARES="$DEERFLOW_DIR/backend/packages/harness/deerflow/agents/middlewares"
  if [ -d "$BRIDGE_DIR/patches/middlewares" ] && [ -d "$DF_MIDDLEWARES" ]; then
    cp "$BRIDGE_DIR/patches/middlewares/"*.py "$DF_MIDDLEWARES/"
    ok "Applied middleware patches (loop reset + exact-call model concurrency)"
  fi

  # (b4) Embedded subagent safety overlay. Apply narrow idempotent transforms
  #     so the active vendor version keeps all tracing/session/token behavior
  #     while passing the exact AppConfig, inheriting the active model from
  #     configurable state, and rejecting provider fallbacks as failed tasks.
  SUBAGENT_OVERLAY="$BRIDGE_DIR/patches/apply_subagent_overlays.py"
  if [ ! -f "$SUBAGENT_OVERLAY" ]; then
    warn "Required subagent safety overlay is missing: $SUBAGENT_OVERLAY"
    exit 1
  fi
  if python3 "$SUBAGENT_OVERLAY" "$DEERFLOW_DIR" >/dev/null; then
    ok "Applied subagent provider inheritance + failure boundary"
  else
    warn "Could not apply required subagent overlay; inspect upstream runtime drift"
    exit 1
  fi

  # (b5) Lead-agent factory overlay: YAML ``trim_tokens_to_summarize: null`` is
  #     deliberate (summarize the complete discarded segment), and a null
  #     summarization model must inherit the active run model rather than the
  #     first configured provider. This tracked idempotent overlay preserves
  #     both contracts across a clean clone. Unlike optional enhancements, a
  #     failed safety overlay aborts setup so a broken runtime cannot launch.
  LEAD_AGENT_OVERLAY="$BRIDGE_DIR/patches/apply_lead_agent_overlays.py"
  if [ ! -f "$LEAD_AGENT_OVERLAY" ]; then
    warn "Required lead-agent summarization overlay is missing: $LEAD_AGENT_OVERLAY"
    exit 1
  fi
  if python3 "$LEAD_AGENT_OVERLAY" "$DEERFLOW_DIR" >/dev/null; then
    ok "Applied lead-agent summarization overlay (null trim + model inheritance)"
  else
    warn "Could not apply required lead-agent summarization overlay; inspect upstream factory drift"
    exit 1
  fi

  # (b6) Model-factory metadata overlay: ``context_window_tokens`` controls
  #     local research/synthesis budgeting. It must not be forwarded as an
  #     OpenAI-compatible request parameter.
  MODEL_FACTORY_OVERLAY="$BRIDGE_DIR/patches/apply_model_factory_overlays.py"
  if [ -f "$MODEL_FACTORY_OVERLAY" ]; then
    if python3 "$MODEL_FACTORY_OVERLAY" "$DEERFLOW_DIR" >/dev/null; then
      ok "Applied model-factory metadata boundary"
    else
      warn "Could not apply model-factory overlay; inspect upstream factory drift"
    fi
  fi

  # (c) Ready-to-use config.yaml (claude/minimax/deepseek/qwen/glm/codex stanzas,
  #     all keys as $VAR — no secrets). NEVER clobber an existing config.yaml:
  #     it is gitignored upstream and may carry the user's own tuning.
  if [ ! -f "$DEERFLOW_DIR/config.yaml" ]; then
    if [ -f "$BRIDGE_DIR/config.yaml" ]; then
      cp "$BRIDGE_DIR/config.yaml" "$DEERFLOW_DIR/config.yaml"
      ok "Installed config.yaml (7 provider stanzas; keys read from .env via \$VAR)"
    fi
  else
    info "deer-flow/config.yaml already exists — leaving it. Diff it against"
    info "    deerflow_bridge/config.yaml to pick up new provider stanzas."
  fi
fi

# 3) Build DeerFlow's isolated venv. DeerFlow 2.0 pins Python 3.12
#    (deer-flow/backend/.python-version), so build against 3.12 to match its
#    uv.lock exactly. Guarded so a build failure here does not abort the setup.
if [ -d "$DEERFLOW_DIR/backend" ]; then
  if have uv; then
    if UV_PROJECT_ENVIRONMENT="$DEERFLOW_DIR/backend/.venv" \
         uv sync --project "$DEERFLOW_DIR/backend" --python 3.12; then
      ok "DeerFlow venv ready ($DEERFLOW_DIR/backend/.venv, Python 3.12)"
    else
      warn "DeerFlow 'uv sync' failed. The rest of the setup is unaffected;"
      warn "you can retry with:"
      warn "    UV_PROJECT_ENVIRONMENT=\"$DEERFLOW_DIR/backend/.venv\" \\"
      warn "      uv sync --project \"$DEERFLOW_DIR/backend\" --python 3.12"
    fi
  else
    warn "Skipping DeerFlow venv — uv is not available (see install hint above)."
  fi
else
  warn "deer-flow not available at: $DEERFLOW_DIR"
  warn "Deep research (pipeline stage 1) needs it. Re-run ./setup.sh once you have"
  warn "network access, or set DEERFLOW_DIR to an existing checkout."
fi

# ---------------------------------------------------------------------------
# 5b) OPTIONAL — DRF-2 preview (next-generation architecture)
# ---------------------------------------------------------------------------
# DRF-2 (drf2/ + REDESIGN.md) rebuilds the pipeline around the DeerFlow 2.0
# super-agent harness: methodology as skills, the knowledge graph and OASIS
# simulation exposed as MCP servers, and a deterministic Pipeline Driver for
# gates/resume/ensemble. It is a PREVIEW — the legacy pipeline installed above
# remains the working system. This step is OFF by default; opt in with:
#     SETUP_DRF2=1 ./setup.sh
# It only installs the engines' extra dependency (the python 'mcp' package,
# pinned per drf2/engines/kg/requirements.txt) into backend/.venv and prints
# the registration / run commands. Idempotent and guarded like everything else.
if [ "${SETUP_DRF2:-0}" = "1" ]; then
  step "Setting up DRF-2 preview (optional, SETUP_DRF2=1)"

  DRF2_KG_REQS="$ROOT_DIR/drf2/engines/kg/requirements.txt"
  DRF2_SIM_REQS="$ROOT_DIR/drf2/engines/simulation/requirements.txt"
  BACKEND_PY="$ROOT_DIR/backend/.venv/bin/python"

  if [ ! -d "$ROOT_DIR/drf2" ]; then
    warn "drf2/ directory not found — skipping DRF-2 setup."
  elif [ ! -x "$BACKEND_PY" ]; then
    warn "backend/.venv is not built yet (the engines run from it). Re-run"
    warn "    ./setup.sh so the backend 'uv sync' step succeeds, then retry with"
    warn "    SETUP_DRF2=1 ./setup.sh"
  else
    # Install the MCP transport dependency into backend/.venv. Both engine
    # requirement files pin only 'mcp' (kg: mcp>=1.24.0, sim: mcp>=1.2);
    # everything else is reused from the legacy backend venv by import.
    DRF2_MCP_OK=0
    if have uv; then
      if uv pip install --python "$BACKEND_PY" \
           -r "$DRF2_KG_REQS" -r "$DRF2_SIM_REQS"; then
        DRF2_MCP_OK=1
      fi
    elif [ -x "$ROOT_DIR/backend/.venv/bin/pip" ]; then
      if "$ROOT_DIR/backend/.venv/bin/pip" install \
           -r "$DRF2_KG_REQS" -r "$DRF2_SIM_REQS"; then
        DRF2_MCP_OK=1
      fi
    fi
    if [ "$DRF2_MCP_OK" = "1" ]; then
      ok "DRF-2 engine dependency installed ('mcp' in backend/.venv)"
    else
      warn "Could not install the 'mcp' package into backend/.venv. Retry with:"
      warn "    uv pip install --python \"$BACKEND_PY\" 'mcp>=1.24.0'"
    fi

    # How to register the two MCP engines + run the harness/driver. The two
    # engines are stdio MCP servers the harness SPAWNS per extensions_config
    # (you do not start them by hand); FalkorDB must be reachable for the KG
    # engine. Full details: drf2/README.md and drf2/engines/*/README.md.
    cat <<DRF2NEXT
  DRF-2 next steps (preview — the legacy pipeline stays authoritative):

  1) Register the two MCP engines with the harness. drf2/config/extensions_config.json
     already carries both stdio server entries; re-point its absolute paths
     (venv python, PYTHONPATH) at this checkout if needed:
       drf2-kg:         backend/.venv/bin/python -m drf2.engines.kg.server --graph-id <id>
       drf2-simulation: backend/.venv/bin/python drf2/engines/simulation/server.py

  2) Start the DeerFlow 2.0 harness with the DRF-2 config:
       cd "$ROOT_DIR/deer-flow-2.0.0"
       export DEER_FLOW_CONFIG_PATH="$ROOT_DIR/drf2/config/config.yaml"
       export DEER_FLOW_EXTENSIONS_CONFIG_PATH="$ROOT_DIR/drf2/config/extensions_config.json"
       export PYTHONPATH="$ROOT_DIR:\${PYTHONPATH:-}"
       make dev        # gateway :8001, UI :3000, nginx :2026

  3) Drive a deterministic pipeline run (health gates, resume, ensemble):
       cd "$ROOT_DIR"
       PYTHONPATH="$ROOT_DIR" backend/.venv/bin/python -m drf2.driver.cli \\
         run --question "..." --config drf2/config/config.yaml
     (add --dry-run to smoke-test the whole state machine offline; see
      drf2/README.md §3 and drf2/engines/*/README.md for details)
DRF2NEXT
  fi
fi

# ---------------------------------------------------------------------------
# 6) Next steps
# ---------------------------------------------------------------------------
step "Next steps"
cat <<NEXT
  1) Knowledge graph: runs locally (Graphiti + embedded FalkorDB). No API key,
     no external service. Configurable via GRAPH_BACKEND=auto in: $ENV_FILE
     (auto -> embedded FalkorDB; or 'kuzu', or point FALKORDB_HOST at a server).

  2) Model provider: currently LLM_PROVIDER=$LLM_PROVIDER (DEERFLOW_MODEL=$DEERFLOW_MODEL).
       • claude-cli / codex-cli use your local CLI — no API key needed.
       • Change it any time: re-run ./setup.sh (interactive picker), edit .env
         (LLM_PROVIDER=openai|kimi|minimax|deepseek|qwen|glm + LLM_API_KEY), or
         switch at runtime from the UI Settings menu — which also has a
         "Test connection" button to verify your API key in one click.
       • To run deep research on a specific model, set DEERFLOW_MODEL to
         claude | minimax | deepseek | qwen | glm | codex | kimi.

  3) Verify the environment is ready (tool versions, both venvs, the DeerFlow
     overlay, and credentials for the provider you picked) — takes seconds:
       ${C_BOLD}npm run doctor${C_RESET}
     Fix any ✗ it reports and re-run until it prints "All checks passed".

  4) Start everything (backend :5001 + frontend :3000):
       ${C_BOLD}npm run dev${C_RESET}

  5) Open the dashboard, type a question, and click
     "Run research + simulate + forecast":
       ${C_BOLD}http://localhost:3000/research${C_RESET}
NEXT

printf '\n'
ok "Setup complete."
