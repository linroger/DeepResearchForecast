#!/usr/bin/env bash
#
# setup_datamcps.sh — build the vendored official-data MCP servers (datamcps/)
# ---------------------------------------------------------------------------
# Deep research and the forecast report query six third-party MCP servers for
# official statistics: FRED, BLS, BIS, IMF, World Bank Data360 (wb) and US Gov
# Open Data (usgov). Their sources are committed unmodified under datamcps/;
# their build outputs (node_modules/, dist/, build/, .venv/) are gitignored, so
# a fresh clone runs this once (./setup.sh calls it for you):
#
#   npm run setup:datamcps                     (or: bash scripts/setup_datamcps.sh)
#   bash scripts/setup_datamcps.sh fred bls    # only the named servers
#   bash scripts/setup_datamcps.sh --check     # report status, build nothing
#   bash scripts/setup_datamcps.sh --force     # rebuild even when up to date
#
# Idempotent: a server whose build output is newer than its sources and
# lockfile is skipped in well under a second. Warn-and-continue: a server that
# cannot be built (missing tool, old node, network failure) is reported and the
# others still build; at run time an unbuilt server is simply "unavailable",
# never a failed run. SETUP_DATAMCPS=0 skips the whole step.
#
# Recipes (vendored sources and lockfiles are never modified):
#   fred   pnpm install --frozen-lockfile --ignore-scripts && pnpm run build
#          (fallback: npm install --no-package-lock --ignore-scripts && npm run build)
#   bls    npm ci && npm run build
#   bis    npm ci (npm install without a lockfile); no build step, tsx runs src/
#   usgov  npm ci (its prepare script compiles dist/); needs node >= 22
#   imf    uv venv --python 3.12 .venv && uv pip install . "mcp[cli]>=1.9.1,<2"
#          (never uv sync: the shipped uv.lock is stale and mcp 2.x breaks it)
#   wb     uv sync --frozen --no-dev (Python >= 3.11, fetched by uv if needed)
#
# Settings (an exported variable wins, else the repo .env): DATA_SOURCES_DIR
# (servers root, default <repo>/datamcps), DATA_SOURCES_NODE (node binary;
# default: node on PATH, then ~/.local/bin, /opt/homebrew/bin, /usr/local/bin).
#
# Exit code: 0 = every selected server is ready (or SETUP_DATAMCPS=0);
# 1 = at least one server is not ready (see the summary table); 64 = bad usage.
# ---------------------------------------------------------------------------
# No `set -e`: every step is checked explicitly so one server's failure is
# reported and the remaining servers still build.
set -u -o pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")/.." && pwd)"
ALL_SERVERS="fred bls bis imf wb usgov"

if [ -t 1 ]; then
  C_RESET="$(printf '\033[0m')"; C_BOLD="$(printf '\033[1m')"
  C_GREEN="$(printf '\033[32m')"; C_YELLOW="$(printf '\033[33m')"; C_CYAN="$(printf '\033[36m')"
else
  C_RESET="" C_BOLD="" C_GREEN="" C_YELLOW="" C_CYAN=""
fi
ok()   { printf '%s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
info() { printf '%s›%s %s\n' "$C_CYAN" "$C_RESET" "$*"; }
step() { printf '\n%s== %s ==%s\n' "$C_BOLD" "$*" "$C_RESET"; }
have() { command -v "$1" >/dev/null 2>&1; }

FORCE=0
CHECK_ONLY=0
SELECTED=""
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --check) CHECK_ONLY=1 ;;
    -h|--help)
      # The header doc block (lines 3-37) is the help text.
      sed -n '3,37p' "$SCRIPT_SOURCE" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    fred|bls|bis|imf|wb|usgov)
      case " $SELECTED " in *" $arg "*) ;; *) SELECTED="$SELECTED $arg" ;; esac ;;
    *)
      printf 'setup_datamcps.sh: unknown argument %s (servers: %s; options: --check --force --help)\n' \
        "$arg" "$ALL_SERVERS" >&2
      exit 64 ;;
  esac
done
SELECTED="${SELECTED# }"
[ -n "$SELECTED" ] || SELECTED="$ALL_SERVERS"

if [ "${SETUP_DATAMCPS:-1}" = "0" ]; then
  info "SETUP_DATAMCPS=0 — skipping the data-source MCP server builds."
  exit 0
fi

# envval KEY -> first active KEY=value in the repo .env (quotes and a
# space-prefixed inline comment stripped; empty when absent). Same parsing as
# scripts/doctor.sh.
envval() {
  [ -f "$ROOT_DIR/.env" ] || { echo ""; return; }
  grep -E "^[[:space:]]*$1=" "$ROOT_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '"' \
    | sed -E 's/[[:space:]]+#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//' || true
}

# cfgval KEY -> an exported KEY for this invocation wins, else the repo .env
# (the precedence scripts/doctor.sh uses for every setting it reads).
cfgval() {
  local value="${!1:-}"
  [ -n "$value" ] || value="$(envval "$1")"
  printf '%s\n' "$value"
}

DATAMCPS_DIR="$(cfgval DATA_SOURCES_DIR)"
DATAMCPS_DIR="${DATAMCPS_DIR:-$ROOT_DIR/datamcps}"
case "$DATAMCPS_DIR" in
  /*) ;;
  *) DATAMCPS_DIR="$ROOT_DIR/$DATAMCPS_DIR" ;;
esac

# ---------------------------------------------------------------------------
# Toolchain discovery (node / npm / pnpm / uv)
# ---------------------------------------------------------------------------
# node resolution mirrors the runtime (data_mcp.default_server_specs and the
# orchestrator's DATA_SOURCES_NODE forwarding): an explicit DATA_SOURCES_NODE
# wins; otherwise PATH, then the usual per-user / Homebrew install locations.
NODE_SETTING="$(cfgval DATA_SOURCES_NODE)"
NODE_BIN=""
NODE_PROBLEM=""
if [ -n "$NODE_SETTING" ]; then
  if [ -x "$NODE_SETTING" ] && [ ! -d "$NODE_SETTING" ]; then
    NODE_BIN="$NODE_SETTING"
  else
    NODE_PROBLEM="DATA_SOURCES_NODE=$NODE_SETTING is not an executable file"
  fi
else
  for cand in "$(command -v node 2>/dev/null || true)" \
              "$HOME/.local/bin/node" /opt/homebrew/bin/node /usr/local/bin/node; do
    if [ -n "$cand" ] && [ -x "$cand" ] && [ ! -d "$cand" ]; then
      NODE_BIN="$cand"
      break
    fi
  done
  [ -n "$NODE_BIN" ] || NODE_PROBLEM="node not found (install Node.js >= 22 or set DATA_SOURCES_NODE)"
fi

NODE_MAJOR=0
NODE_DIR=""
NPM_BIN=""
if [ -n "$NODE_BIN" ]; then
  NODE_VERSION="$("$NODE_BIN" -v 2>/dev/null | sed 's/^v//')"
  NODE_MAJOR="${NODE_VERSION%%.*}"
  case "$NODE_MAJOR" in
    ''|*[!0-9]*)
      NODE_PROBLEM="$NODE_BIN does not report a version (broken node install?)"
      NODE_MAJOR=0 ;;
  esac
  NODE_DIR="$(dirname "$NODE_BIN")"
  # The npm shipped next to this node, so lifecycle scripts run on the same node.
  if [ -x "$NODE_DIR/npm" ]; then
    NPM_BIN="$NODE_DIR/npm"
  else
    NPM_BIN="$(command -v npm 2>/dev/null || true)"
  fi
fi

PNPM_BIN="$(command -v pnpm 2>/dev/null || true)"
if [ -z "$PNPM_BIN" ]; then
  for cand in "$HOME/Library/pnpm/pnpm" "$HOME/.local/share/pnpm/pnpm"; do
    if [ -x "$cand" ]; then PNPM_BIN="$cand"; break; fi
  done
fi
UV_BIN="$(command -v uv 2>/dev/null || true)"
if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
fi

# Run a node-ecosystem command with the chosen node first on PATH.
with_node() { PATH="$NODE_DIR:$PATH" "$@"; }

# ---------------------------------------------------------------------------
# Freshness checks
# ---------------------------------------------------------------------------
# first_newer_input MARKER PATH... -> the first regular input file (searched
# recursively) modified after MARKER; empty when every input is older. Editor
# and interpreter litter never counts as a source change.
first_newer_input() {
  local marker="$1"; shift
  local existing=() path
  for path in "$@"; do
    [ -e "$path" ] && existing+=("$path")
  done
  [ "${#existing[@]}" -gt 0 ] || return 0
  find "${existing[@]}" -type f -newer "$marker" \
    ! -name '.DS_Store' ! -name '*.pyc' ! -path '*/__pycache__/*' ! -path '*/node_modules/*' \
    -print 2>/dev/null | head -n 1 || true
}

# is_fresh MARKER INPUT... -> success when MARKER exists and no input is newer
# (always "stale" under --force).
is_fresh() {
  local marker="$1"; shift
  [ "$FORCE" -eq 0 ] || return 1
  [ -f "$marker" ] || return 1
  [ -z "$(first_newer_input "$marker" "$@")" ]
}

# first_existing PATH... -> the first path that exists (empty when none).
first_existing() {
  local path
  for path in "$@"; do
    if [ -e "$path" ]; then printf '%s\n' "$path"; return 0; fi
  done
  return 0
}

# Mark the build outputs fresh after a successful build so the next run's
# mtime comparison converges even when a tool left an output untouched.
touch_markers() {
  local path
  for path in "$@"; do
    [ -e "$path" ] && touch "$path"
  done
  return 0
}

# ---------------------------------------------------------------------------
# Per-server results (bash 3.2 compatible: no associative arrays)
# ---------------------------------------------------------------------------
ROWS=()
NOT_READY=0
record() { # server status detail
  ROWS+=("$1|$2|$3")
  case "$2" in
    built|up-to-date|ready) ;;
    *) NOT_READY=$((NOT_READY+1)) ;;
  esac
}

# need_node SERVER MIN_MAJOR -> success when a usable node >= MIN_MAJOR and its
# npm exist; otherwise records the server as skipped with the reason.
need_node() {
  local server="$1" min="$2"
  if [ -z "$NODE_BIN" ] || [ -n "$NODE_PROBLEM" ]; then
    warn "$server: ${NODE_PROBLEM:-node not found} — skipped."
    record "$server" skipped "${NODE_PROBLEM:-node not found}"
    return 1
  fi
  if [ "$NODE_MAJOR" -lt "$min" ]; then
    warn "$server: needs node >= $min but $NODE_BIN is v$NODE_VERSION — skipped (set DATA_SOURCES_NODE to a newer node)."
    record "$server" skipped "node >= $min required (found v$NODE_VERSION)"
    return 1
  fi
  if [ -z "$NPM_BIN" ]; then
    warn "$server: npm not found next to $NODE_BIN or on PATH — skipped."
    record "$server" skipped "npm not found"
    return 1
  fi
  return 0
}

need_uv() {
  local server="$1"
  if [ -z "$UV_BIN" ]; then
    warn "$server: uv not found — skipped (curl -LsSf https://astral.sh/uv/install.sh | sh)."
    record "$server" skipped "uv not found"
    return 1
  fi
  return 0
}

# need_sources SERVER DIR MANIFEST -> success when the vendored sources exist.
need_sources() {
  if [ ! -f "$2/$3" ]; then
    warn "$1: sources not found at $2 — skipped."
    record "$1" skipped "sources missing ($2)"
    return 1
  fi
  return 0
}

# report_stale SERVER DETAIL -> --check mode result for an out-of-date server.
report_stale() {
  warn "$1: $2"
  record "$1" stale "$2"
}

# finish_build SERVER STARTED_AT ENTRY MARKER... -> verify the runtime entry
# exists, refresh the markers and record the outcome.
finish_build() {
  local server="$1" started="$2" entry="$3"; shift 3
  if [ ! -e "$entry" ]; then
    warn "$server: build finished but ${entry#"$DATAMCPS_DIR"/} is missing."
    record "$server" failed "entry missing after build"
    return 1
  fi
  touch_markers "$@"
  ok "$server: built in $((SECONDS - started))s (${entry#"$DATAMCPS_DIR"/})"
  record "$server" built "${entry#"$DATAMCPS_DIR"/}"
  return 0
}

# ---------------------------------------------------------------------------
# Node servers
# ---------------------------------------------------------------------------
# build_npm_server SERVER DIR ENTRY MIN_NODE BUILD_MODE
#   BUILD_MODE: "build" (npm ci, then npm run build), "prepare" (npm ci runs
#   the package's prepare script, which builds; a sources-only change reruns
#   npm run build), "none" (dependencies only).
build_npm_server() {
  local server="$1" dir="$2" entry="$3" min="$4" mode="$5"
  need_sources "$server" "$dir" package.json || return 0
  need_node "$server" "$min" || return 0
  local lock="$dir/package-lock.json"
  local deps_marker="$dir/node_modules/.package-lock.json"
  local deps_fresh=0 build_fresh=0
  is_fresh "$deps_marker" "$dir/package.json" "$lock" && deps_fresh=1
  if [ "$mode" = "none" ]; then
    build_fresh=1
    [ -e "$entry" ] || build_fresh=0
  else
    is_fresh "$entry" "$dir/package.json" "$lock" "$dir/tsconfig.json" "$dir/src" && build_fresh=1
  fi
  if [ "$deps_fresh" -eq 1 ] && [ "$build_fresh" -eq 1 ]; then
    ok "$server: up to date (${entry#"$DATAMCPS_DIR"/})"
    record "$server" up-to-date "${entry#"$DATAMCPS_DIR"/}"
    return 0
  fi
  if [ "$CHECK_ONLY" -eq 1 ]; then
    if [ "$deps_fresh" -eq 0 ]; then report_stale "$server" "dependencies not installed or out of date"
    else report_stale "$server" "build output missing or older than sources"; fi
    return 0
  fi

  local started="$SECONDS"
  if [ "$deps_fresh" -eq 0 ]; then
    info "$server: installing dependencies (npm, node v$NODE_VERSION)…"
    local install_ok=0 install_cmd
    if [ -f "$lock" ]; then
      install_cmd="npm ci"
      with_node "$NPM_BIN" ci --prefix "$dir" --no-audit --no-fund && install_ok=1
    else
      install_cmd="npm install"
      with_node "$NPM_BIN" install --prefix "$dir" --no-audit --no-fund --no-package-lock && install_ok=1
    fi
    if [ "$install_ok" -ne 1 ]; then
      warn "$server: $install_cmd failed — retry: $install_cmd --prefix \"$dir\""
      record "$server" failed "$install_cmd failed"
      return 0
    fi
  fi
  # npm ci already ran the prepare build when it reinstalled dependencies.
  if [ "$mode" = "build" ] || { [ "$mode" = "prepare" ] && [ "$deps_fresh" -eq 1 ]; }; then
    info "$server: compiling…"
    if ! with_node "$NPM_BIN" run build --prefix "$dir"; then
      warn "$server: build failed — retry: npm run build --prefix \"$dir\""
      record "$server" failed "npm run build failed"
      return 0
    fi
  fi
  finish_build "$server" "$started" "$entry" "$deps_marker" "$entry" || true
}

build_fred() {
  local server=fred dir="$DATAMCPS_DIR/fred-mcp-server-main"
  local entry="$dir/build/index.js" lock="$dir/pnpm-lock.yaml"
  need_sources "$server" "$dir" package.json || return 0
  need_node "$server" 18 || return 0
  # pnpm records its install in .modules.yaml; the npm fallback in .package-lock.json.
  local deps_marker
  deps_marker="$(first_existing "$dir/node_modules/.modules.yaml" "$dir/node_modules/.package-lock.json")"
  local deps_fresh=0 build_fresh=0
  [ -n "$deps_marker" ] && is_fresh "$deps_marker" "$dir/package.json" "$lock" && deps_fresh=1
  is_fresh "$entry" "$dir/package.json" "$lock" "$dir/tsconfig.json" "$dir/src" && build_fresh=1
  if [ "$deps_fresh" -eq 1 ] && [ "$build_fresh" -eq 1 ]; then
    ok "$server: up to date (${entry#"$DATAMCPS_DIR"/})"
    record "$server" up-to-date "${entry#"$DATAMCPS_DIR"/}"
    return 0
  fi
  if [ "$CHECK_ONLY" -eq 1 ]; then
    if [ "$deps_fresh" -eq 0 ]; then report_stale "$server" "dependencies not installed or out of date"
    else report_stale "$server" "build output missing or older than sources"; fi
    return 0
  fi

  local started="$SECONDS" tool=""
  if [ "$deps_fresh" -eq 0 ]; then
    if [ -n "$PNPM_BIN" ]; then
      info "$server: installing dependencies (pnpm, frozen lockfile)…"
      if with_node "$PNPM_BIN" --dir "$dir" install --frozen-lockfile --ignore-scripts; then
        tool=pnpm
      else
        warn "$server: pnpm install failed — falling back to npm."
      fi
    else
      info "$server: pnpm not found — installing with npm instead."
    fi
    if [ -z "$tool" ]; then
      if with_node "$NPM_BIN" install --prefix "$dir" --no-audit --no-fund --no-package-lock --ignore-scripts; then
        tool=npm
      else
        warn "$server: dependency install failed — retry: pnpm --dir \"$dir\" install --frozen-lockfile --ignore-scripts"
        record "$server" failed "dependency install failed"
        return 0
      fi
    fi
  elif [ -n "$PNPM_BIN" ] && [ -f "$dir/node_modules/.modules.yaml" ]; then
    tool=pnpm
  else
    tool=npm
  fi
  info "$server: compiling ($tool run build)…"
  local build_ok=0
  if [ "$tool" = pnpm ]; then
    with_node "$PNPM_BIN" --dir "$dir" run build && build_ok=1
  else
    with_node "$NPM_BIN" run build --prefix "$dir" && build_ok=1
  fi
  if [ "$build_ok" -ne 1 ]; then
    warn "$server: build failed — retry: pnpm --dir \"$dir\" run build"
    record "$server" failed "build failed"
    return 0
  fi
  deps_marker="$(first_existing "$dir/node_modules/.modules.yaml" "$dir/node_modules/.package-lock.json")"
  finish_build "$server" "$started" "$entry" "$deps_marker" "$entry" || true
}

build_bls() {
  build_npm_server bls "$DATAMCPS_DIR/bls_mcp-main" \
    "$DATAMCPS_DIR/bls_mcp-main/dist/index.js" 18 build
}

build_bis() {
  # No compile step: bin/cli.js registers tsx and imports src/server.ts, so the
  # runtime only needs installed dependencies (tsx among them).
  build_npm_server bis "$DATAMCPS_DIR/mcp-bis-main" \
    "$DATAMCPS_DIR/mcp-bis-main/node_modules/tsx/package.json" 18 none
}

build_usgov() {
  build_npm_server usgov "$DATAMCPS_DIR/us-gov-open-data-mcp-main" \
    "$DATAMCPS_DIR/us-gov-open-data-mcp-main/dist/server.js" 22 prepare
}

# ---------------------------------------------------------------------------
# Python servers
# ---------------------------------------------------------------------------
build_imf() {
  local server=imf dir="$DATAMCPS_DIR/imf-data-mcp-main"
  local venv="$dir/.venv" entry="$dir/.venv/bin/imf-data-mcp"
  need_sources "$server" "$dir" pyproject.toml || return 0
  need_uv "$server" || return 0
  # Non-editable install: a source change needs a reinstall, so the package
  # sources count as inputs (uv.lock is deliberately not used, see header).
  if is_fresh "$entry" "$dir/pyproject.toml" "$dir/imf_data_mcp"; then
    ok "$server: up to date (${entry#"$DATAMCPS_DIR"/})"
    record "$server" up-to-date "${entry#"$DATAMCPS_DIR"/}"
    return 0
  fi
  if [ "$CHECK_ONLY" -eq 1 ]; then
    report_stale "$server" "venv missing or older than sources"
    return 0
  fi
  local started="$SECONDS"
  if [ ! -x "$venv/bin/python" ]; then
    info "$server: creating $venv (Python 3.12)…"
    if ! "$UV_BIN" venv --python 3.12 "$venv"; then
      warn "$server: uv venv failed — retry: uv venv --python 3.12 \"$venv\""
      record "$server" failed "uv venv failed"
      return 0
    fi
  fi
  info "$server: installing the server (mcp pinned below 2.x)…"
  if ! "$UV_BIN" pip install --python "$venv/bin/python" --reinstall-package imf-data-mcp \
       "$dir" "mcp[cli]>=1.9.1,<2"; then
    warn "$server: install failed — retry: uv pip install --python \"$venv/bin/python\" \"$dir\" \"mcp[cli]>=1.9.1,<2\""
    record "$server" failed "uv pip install failed"
    return 0
  fi
  finish_build "$server" "$started" "$entry" "$entry" || true
}

build_wb() {
  local server=wb dir="$DATAMCPS_DIR/data360-mcp-dev"
  local marker="$dir/.venv/pyvenv.cfg" entry="$dir/.venv/bin/python"
  need_sources "$server" "$dir" pyproject.toml || return 0
  need_uv "$server" || return 0
  # uv sync installs the project editable, so only the manifest and lockfile
  # decide whether the venv is current.
  if [ -x "$entry" ] && is_fresh "$marker" "$dir/pyproject.toml" "$dir/uv.lock"; then
    ok "$server: up to date (${entry#"$DATAMCPS_DIR"/})"
    record "$server" up-to-date "${entry#"$DATAMCPS_DIR"/}"
    return 0
  fi
  if [ "$CHECK_ONLY" -eq 1 ]; then
    report_stale "$server" "venv missing or older than uv.lock"
    return 0
  fi
  local started="$SECONDS"
  info "$server: syncing the locked environment (uv sync --frozen --no-dev)…"
  # The project's own .venv, never an inherited UV_PROJECT_ENVIRONMENT/VIRTUAL_ENV.
  if ! env -u UV_PROJECT_ENVIRONMENT -u VIRTUAL_ENV \
       "$UV_BIN" sync --directory "$dir" --frozen --no-dev; then
    warn "$server: uv sync failed — retry: uv sync --directory \"$dir\" --frozen --no-dev"
    record "$server" failed "uv sync failed"
    return 0
  fi
  finish_build "$server" "$started" "$entry" "$marker" || true
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if [ "$CHECK_ONLY" -eq 1 ]; then
  step "Data-source MCP servers (check only): $DATAMCPS_DIR"
else
  step "Building data-source MCP servers: $DATAMCPS_DIR"
fi
if [ -n "$NODE_BIN" ] && [ -z "$NODE_PROBLEM" ]; then
  info "node: $NODE_BIN (v$NODE_VERSION)"
fi
if [ ! -d "$DATAMCPS_DIR" ]; then
  warn "servers root not found: $DATAMCPS_DIR (set DATA_SOURCES_DIR) — nothing to build."
  exit 1
fi

for server in $SELECTED; do
  "build_$server"
done

step "Data-source MCP servers: summary"
printf '  %-6s %-11s %s\n' "server" "status" "detail"
for row in ${ROWS[@]+"${ROWS[@]}"}; do
  r_server="${row%%|*}"; rest="${row#*|}"
  r_status="${rest%%|*}"; r_detail="${rest#*|}"
  printf '  %-6s %-11s %s\n' "$r_server" "$r_status" "$r_detail"
done

if [ "$NOT_READY" -gt 0 ]; then
  warn "$NOT_READY data-source server(s) not ready — research runs continue without them."
  exit 1
fi
ok "All selected data-source MCP servers are ready."
exit 0
