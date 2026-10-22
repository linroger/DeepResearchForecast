# ops-shell-deps-ci — Shell entrypoints, dependencies, CI, project harness files

Scope (all read line by line on branch `main`, working tree as on disk 2026-10-11):
`setup.sh` (848 lines), `scripts/start.sh` (699), `scripts/doctor.sh` (518), `scripts/smoke.sh` (540),
`scripts/setup_port80.sh` (131), `init.sh` (26), `package.json` (28), `backend/pyproject.toml` (97),
`backend/requirements.txt` (56), `.github/workflows/ci.yml` (50), `.env.example` (707, structure +
names), `feature_list.json` (175), `backend/CLAUDE.md` (10).
Out-of-slice files were opened only to resolve what a call does (anchors given where used).

---

## Purpose & position in the pipeline

This slice holds no pipeline logic. It is the operations shell around the Flask backend and the Vue frontend:

- **Install:** `setup.sh` checks tools, picks an LLM provider and writes `.env`, installs npm deps,
  builds `backend/.venv` with uv (Python 3.12), assembles the gitignored `deer-flow/` research engine
  from the vendored `deer-flow-2.0.0/` (or a pinned clone), applies the `deerflow_bridge/` overlay and builds
  `deer-flow/backend/.venv` (setup.sh:5-27, 469-736).
- **Start/stop:** `scripts/start.sh` (`npm start` / `npm stop`) starts the backend
  (`backend/.venv/bin/python run.py`, :5001) and the frontend (`npm run dev` → Vite, :3000) as detached processes
  with PID files. It gates on app-specific readiness signatures and can stream the logs plus the pipeline-stage
  progress read from `backend/uploads/pipelines/*/pipeline_state.json` (start.sh:3-21, 361-382, 590-593).
  `npm run dev` runs the same two services in the foreground through `concurrently` (package.json:11).
- **Health checks:** `scripts/doctor.sh` (`npm run doctor`) is an offline check of tools, venvs, the DeerFlow
  overlay and `.env`. `--deep` adds live-key, embed-cache and disk probes through `backend/scripts/preflight.py`
  (doctor.sh:5-29, 236-276).
- **Smoke test:** `scripts/smoke.sh` (`npm run smoke`) is an offline contract test of pipeline stages 2-6 with a
  stub LLM. It can optionally build a real Graphiti graph and run an OASIS micro-sim (smoke.sh:3-36).
- **Harness:** `init.sh` is a quick byte-compile/presence check named "actor-grounding smoke check" (init.sh:26).
  `feature_list.json` is the agent-harness feature ledger.
- **Dependencies:** `backend/pyproject.toml` is the authoritative uv project. `backend/requirements.txt` is a stale
  pip list. `package.json` holds the npm task aliases.
- **CI:** `.github/workflows/ci.yml` runs three offline jobs: lint plus env-drift, pytest, and compileall.
- **Optional macOS port-80 redirect:** `scripts/setup_port80.sh`.

Every runtime stage (research → graph → simulation → report) is downstream of these scripts. Nothing here runs
in the request path, except that the orchestrator mirrors part of `setup.sh`'s overlay at launch time
(see Cross-module edges).

---

## Walkthrough (source order)

### 1. `setup.sh` — installer (idempotent, re-runnable)

| Block | Anchor | Behavior |
|---|---|---|
| Header contract | setup.sh:3-31 | Claims: checks "node>=18, npm, uv, python3" and "WARNS (never hard-fails)". It has an interactive provider picker, scaffolds `.env`, installs deps and assembles DeerFlow. **Code differs:** node ≥20.19 is required (L89-101) and several overlay failures `exit 1` (L628-640, 660-687). |
| Shell mode | setup.sh:37 | `set -euo pipefail`. Optional steps are guarded with `if`/`\|\| true`. |
| Root + colors | setup.sh:45-63 | `ROOT_DIR` = the script's own dir. Colors only if stdout is a TTY. Helpers `ok/warn/info/step`. |
| Banner | setup.sh:68-76 | Prints "DeepAgentForecast — setup" (old product name). |
| Prereqs | setup.sh:81-146 | `have()`=`command -v`. node: accepted if major≥22, OR 20.x with minor≥19, OR major 21 (L95). Otherwise warn and set `MISSING_PREREQS=1`. The same pattern applies to npm (L108-113), uv (L116-123; prints the install curl), python3 (presence only, any version, L126-132) and git (L135-141). The step never exits. |
| Provider tables | setup.sh:156-187 | Parallel bash-3.2 arrays (no assoc arrays). `PROVIDER_IDS=(claude-cli codex-cli openai kimi minimax deepseek qwen glm)`. Each provider has a needs-key flag, a DeerFlow model (`claude codex claude kimi minimax deepseek qwen glm`; note openai→`claude`), a default base URL, a default model (`gpt-4o-mini`, `kimi-for-coding`, `MiniMax-M3`, `deepseek-chat`, `qwen-plus`, `glm-4.6`) and a mirrored key env (`KIMI_API_KEY`, `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `ZHIPUAI_API_KEY`). |
| Auto-detect default | setup.sh:192-203 | Index 0 (claude-cli) by default. If `claude` is on PATH → 0, else if `codex` → 1, else warn. |
| Existing `.env` wins | setup.sh:207-222 | Greps the first active `LLM_PROVIDER=` line in `.env`, deletes all whitespace (it does not strip quotes or inline comments) and, if the value matches a known id, makes it the menu default. |
| Interactive picker | setup.sh:232-273 | Runs only if stdin is a TTY and `SETUP_NONINTERACTIVE!=1`. Enter or non-numeric input → default; out-of-range → default with a warning. API-key providers get a silent `read -rs` key prompt (L262-269). |
| `.env` scaffold | setup.sh:280-296 | Never overwrites an existing `.env`. If `.env` is missing, copies `.env.example`. If that is also missing, writes a stub with `LLM_PROVIDER=claude-cli` and `GRAPH_BACKEND=auto`. |
| `upsert_env KEY VALUE` | setup.sh:305-322 | awk rewrite into `mktemp "$ENV_FILE.XXXXXX"` followed by `mv`. Replaces the first active `^[[:space:]]*KEY=` line, drops duplicate active lines and appends the key if absent. The value is passed through ENVIRON, so it is literal. |
| Persist choice | setup.sh:324-383 | Interactive: always writes `LLM_PROVIDER`. Keeps the existing `DEERFLOW_MODEL` if the provider is unchanged, otherwise writes the table value. For key providers it writes `LLM_BASE_URL` and `LLM_MODEL_NAME` when the provider changed or the value is empty (L345-354), and writes `LLM_API_KEY` plus the mirrored provider key env (L355-364). Non-interactive: only fills `LLM_PROVIDER`/`DEERFLOW_MODEL` when missing (L369-382). |
| Live key test | setup.sh:389-424 | Runs only if a key was just typed and curl exists. `POST {PROVIDER_BASE}/chat/completions` with `max_tokens:1` and a 25 s timeout. For kimi it adds `User-Agent: claude-cli/1.0.0` (L392-395). The bearer header is fed through `--config -` on stdin so it never appears in argv (L397-410). The response goes to a 0600 mktemp file that is then removed. Codes: 200 ok; 401/403 rejected; `000` unreachable; anything else is "HTTP n". **Network call to the provider.** |
| npm deps | setup.sh:440-462 | `npm run setup` (root plus frontend `npm install`) when package.json has a `"setup"` script, else direct `npm install`s. Failure is a warning. |
| Backend venv | setup.sh:469-481 | `( cd backend && uv sync --python 3.12 )`. Failure is a warning. backend/.python-version=`3.12`. |
| DeerFlow location knobs | setup.sh:500-504 | `DEERFLOW_DIR` (default `$ROOT/deer-flow`), `DEERFLOW_VENDOR_DIR` (default `$ROOT/deer-flow-2.0.0`), `DEERFLOW_REPO` (default `https://github.com/bytedance/deer-flow.git`), `DEERFLOW_REF` (default `799bef6d9dbc3a2cb37ce8177eeeabe2a33d8971`). `BRIDGE_DIR=$ROOT/deerflow_bridge`. |
| Acquire engine | setup.sh:519-569 | Only if `$DEERFLOW_DIR/.git` and `$DEERFLOW_DIR/backend` are both absent. Preferred path: `cp -R $VENDOR $DEERFLOW_DIR` (L521-529). Fallback: `git clone --depth 1`, then (if REF≠main) `git fetch --depth 1 origin $REF && checkout FETCH_HEAD`; failing to pin is only a warning (L530-545). Then it trims runtime-irrelevant files (`.git frontend docs docker contracts scripts .github …`, L556-566). An existing checkout is never re-acquired (L567-568). |
| Overlay (a) | setup.sh:578-581 | `cp deerflow_bridge/deerflow_research.py → deer-flow/deerflow_research.py`. |
| Overlay (a2) | setup.sh:597-609 | Copies the bare-imported modules `market_tools.py search_tools.py cached_fetch.py research_budget.py runtime_skill_sync.py linear_research.py research_gateway.py` into the deer-flow root. The comment says the list must match `_DEPLOYED_BRIDGE_MODULES` in the orchestrator (pipeline_orchestrator.py:1359-1362); parity is pinned by backend/tests/test_deerflow_bridge_sync_guard.py:224-235. |
| Overlay (b) | setup.sh:617-621 | `cp deerflow_bridge/patches/models/*.py → deer-flow/backend/packages/harness/deerflow/models/` (claude_provider, credential_loader, patched_minimax). **setup.sh is the only deployer of these** (backend/tests/test_claude_prompt_cache.py:417-419). |
| Overlay (b2) skills | setup.sh:626-641 | If both skill roots exist, it requires `runtime_skill_sync.py` and **system `python3`**, else **exit 1**. It runs `python3 runtime_skill_sync.py --source-root deerflow_bridge/skills --deployed-public-root deer-flow/skills/public` (CLI: deerflow_bridge/runtime_skill_sync.py:577-585) and prints the JSON result. Failure → **exit 1**. |
| Overlay (b3) middlewares | setup.sh:649-653 | `cp deerflow_bridge/patches/middlewares/*.py → …/deerflow/agents/middlewares/` (loop_detection, model_concurrency, summarization, title, tool_error_handling). |
| Overlay (b4) subagent | setup.sh:659-669 | `python3 patches/apply_subagent_overlays.py <deerflow_dir>` (single positional argv, apply_subagent_overlays.py:408-410). Missing or failing → **exit 1**. |
| Overlay (b5) lead-agent | setup.sh:677-687 | `python3 patches/apply_lead_agent_overlays.py <deerflow_dir>`. Missing or failing → **exit 1**. |
| Overlay (b6) model-factory | setup.sh:692-699 | Optional: runs if the file exists, and failure is only a warning. |
| config.yaml | setup.sh:704-712 | Copies `deerflow_bridge/config.yaml` only if `deer-flow/config.yaml` is absent (never clobbers). It claims "7 provider stanzas"; the bridge file has 8 model entries (claude, antigravity, minimax, deepseek, qwen, glm, codex, kimi at deerflow_bridge/config.yaml:45-251). |
| DeerFlow venv | setup.sh:718-736 | `UV_PROJECT_ENVIRONMENT=deer-flow/backend/.venv uv sync --project deer-flow/backend --python 3.12`. Failure is a warning. |
| DRF-2 preview (opt-in) | setup.sh:750-814 | Only with `SETUP_DRF2=1`. Installs `-r drf2/engines/kg/requirements.txt -r drf2/engines/simulation/requirements.txt` (`mcp>=1.24.0`, `mcp>=1.2`) into backend/.venv via `uv pip install --python` (or venv pip), then prints manual next steps (`make dev` inside `deer-flow-2.0.0`, the `drf2.driver.cli` run command). |
| Next steps | setup.sh:819-848 | Prints the provider summary and `npm run doctor`, `npm run dev`, `http://localhost:3000/research`. Final "Setup complete." |

### 2. `scripts/start.sh` — detached launcher / stopper / attached log follower

Shell mode `set -uo pipefail` (no `-e`) (start.sh:23). It `cd`s to the repo root (L25-28).

**Constants** (start.sh:30-50): `LOG_DIR=logs/` (created). `.backend.pid` and `.frontend.pid` in the repo root.
`PYTHON_BIN=backend/.venv/bin/python`. `WATCHER_SCRIPT=scripts/watch_pipeline_progress.py`.
`PIPELINES_DIR=backend/uploads/pipelines`. Logs go to `logs/backend.out.log` and `logs/frontend.out.log`.
`BACKEND_PORT=${FLASK_PORT:-5001}` (process env only). `FRONTEND_PORT=3000` (hard-coded).
`BACKEND_URL=http://localhost:$PORT/health`, `FRONTEND_URL=http://localhost:3000/`. Timeouts are listed under
Config / env knobs.

**Args** (start.sh:52-66): `--no-open` (NO_OPEN=1), `--detach` (FOLLOW=0), `--stop`. `--help` prints `sed -n '12,21p'`
of itself. Unknown argument → exit 2.

**Process-identity helpers:**
- `_pid_alive` (L68-74): numeric, >1, `kill -0`.
- `_read_pidfile` (L93-98): reads the first line.
- `_canonical_dir` (L100-103): `pwd -P`.
- `_pid_cwd` (L105-112): Linux `/proc/$pid/cwd`, else `lsof -a -p $pid -d cwd -Fn`.
- `_pid_command` (L114-116): `ps -ww -o command=`.
- `_command_matches_role` (L118-133): backend must match `*python*run.py*`. Frontend must match
  `*npm*run dev*|*node_modules/.bin/vite*|*node*/vite*|*node*vite.js*`.
- `_pid_identity_matches` (L135-145): alive, the canonical cwd equals the expected dir (backend/ or frontend/), and
  the command matches the role.
- `_port_owner_pids` (L147-150): `lsof -nP -iTCP:$port -sTCP:LISTEN -t`, deduplicated.
- `_pid_descends_from` (L158-172): walks the ppid chain, at most 64 steps, and stops at 0/1.
- `_pid_tree_owns_port` (L183-191): some listener PID descends from the managed PID (npm → node vite).
- `_service_pid_verified` (L193-197): identity AND tree owns the port.

**`_stop_from_pidfile pidfile label role cwd port`** (start.sh:199-293):
- No file → return 0.
- Dead PID → remove the file, return 0.
- Identity mismatch → **refuse**, remove the untrusted file, return 1.
- Identity OK but the tree does not own the port → refuse, keep the file, return 1.
- Otherwise it collects the verified port owners (descendants with matching identity) and re-verifies.
- Then it sends `kill` (TERM) to the managed PID and to each verified owner that directly owns the port.
- It polls up to 20×0.25 s. Any still-verified process gets `kill -9`. After 0.05 s it checks once more.
- If the process is still owned → error, keep the PID file, return 1. Else remove the PID file, return 0.

**`--stop` path** (start.sh:295-307): requires `lsof` and `ps`. Stops the backend then the frontend. Any refusal →
exit 1 ("Stop incomplete"). Success → exit 0.

**Readiness probes:**
- `_backend_ready` (L309-328): `curl -fsS --max-time $HEALTH_CURL_TIMEOUT` the `/health` URL, then parse it with the
  venv python. The JSON must be a dict with `status=="ok"` and `service=="MiroFish Backend"`, which matches the
  Flask route at backend/app/__init__.py:217-219.
- `_frontend_ready` (L330-336): the body must contain `<title>DeepResearchForecast`,
  `name="description" content="DeepResearchForecast` and `id="app"`, which matches frontend/index.html:7-11.
- `_wait_ready` (L338-359): loops `timeout_s` iterations of probe + `sleep 1`. For managed services it aborts early
  if the PID died or its identity changed.

**Launchers:**
- `_start_backend` (L361-370): subshell `cd backend; nohup $PYTHON_BIN run.py > logs/backend.out.log 2>&1 < /dev/null &`,
  write `$!` to `.backend.pid`, `disown`.
- `_start_frontend` (L372-382): the same, with `nohup npm run dev`. The PID file holds the npm PID.

**`_prepare_backend` / `_prepare_frontend`** (L389-424 / L426-461):
1. If the PID file names a live process that is verified and ready, reuse it (MANAGED=1, no launch).
2. Verified but unready → stop it and replace it.
3. Identity matches but it does not own the port → **error, no duplicate launch**.
4. Otherwise treat it as stale or recycled: remove the PID file without signalling.
5. Next, if an unmanaged external process already passes readiness, accept it (MANAGED stays 0).
6. If something else listens on the port → **refuse** ("wrong or unhealthy responder").
7. Else launch, with MANAGED=1 and STARTED=1.

`_rollback_started_services` (L463-470) stops only what this invocation launched.

**Main sequence** (L472-565):
1. Require curl/lsof/ps and an executable `PYTHON_BIN` (exit 1 "run setup first").
2. Validate the integer knobs (exit 2), `FLASK_PORT` in 1..65535 (exit 2), and the monitor interval as a positive
   finite float via python (exit 2).
3. If following: require `tail` and the watcher script, run the watcher preflight
   `--pipelines-dir backend/uploads/pipelines --once` (failure → exit 1 before any launch), and touch both logs.
4. Prepare the backend, then the frontend (frontend failure rolls back the backend).
5. Wait for backend readiness (60 s) and frontend readiness (30 s), then re-verify PID ownership. Any failure →
   tail 60 lines of both logs, roll back, exit 1.
6. Print the URLs. Unless `--no-open`: `open` on Darwin, `xdg-open` on Linux.
7. `--detach` → exit 0.

**Attached follow mode** (L567-699):
- Starts `tail -n 80 -F` on both logs and the progress watcher as background jobs.
- `trap INT TERM` sets FOLLOW_INTERRUPTED and exits 130. The EXIT trap kills and waits for the followers and prints
  "services remain running … use npm stop".
- Every `MONITOR_INTERVAL` seconds, the loop:
  - restarts a dead follower or watcher at most `FOLLOWER_RESTART_LIMIT` times, then exits 1;
  - re-verifies managed PID identity and port ownership (exit 1 on change);
  - re-probes readiness. Unhealthy longer than `HEALTH_FAILURE_GRACE_SECONDS` → exit 1. Services are **not**
    stopped on this exit. Recovery is logged.

### 3. `scripts/doctor.sh` — environment health check

`set -u` (doctor.sh:31).

**Args** (L39-52): `--deep`, `--pull`, `-h|--help` (prints header lines 3-30 with `# ` stripped). Unknown option → exit 64.

**Reporters** (L61-72): `ok`. `warn` increments `WARNINGS`. `bad` increments `FAILURES`. `dwarn` increments
`DEEP_WARNINGS`.

**`envval KEY`** (L77-81): reads `$ROOT/.env` only (not the process env). Takes the **first** active `KEY=` line,
`cut -d= -f2-`, deletes **all** `"` characters, strips a space-prefixed `# comment` and trims. Missing `.env` → empty.

**Sections:**
- **Tooling** (L83-96): node uses the same version predicate as setup.sh (L87), and failure is `bad`. Missing uv is
  `bad`; missing git is `warn`.
- **Backend venv** (L98-135):
  - Python version: 3.12.x is ok; 3.11.x warns (falkordblite needs 3.12+); an empty version is `bad`; anything else
    warns.
  - `python -c "import camel, oasis, graphiti_core, flask"`, or `bad`.
  - If `backend/scripts/check_env_drift.py` exists: `--strict` drift → `warn`. If `.env` exists: `--pins --strict` →
    `warn` (advisory, never ✗).
  - No venv → `bad`.
- **DeerFlow** (L137-160):
  - `DEERFLOW_DIR` comes from the process env, then `.env`, then `$ROOT/deer-flow`.
  - It requires `deer-flow/backend`, `deerflow_research.py` and `config.yaml`.
  - `DF_PY` comes from `DEERFLOW_PYTHON` (env, then `.env`), else `deer-flow/backend/.venv/bin/python`.
  - It must `import deerflow, langgraph`. Each failure is `bad`.
- **.env** (L162-167): missing → `bad`.
- **Graph backend** (L171-178): `GRAPH_BACKEND` from `.env` (default `auto`). Requires
  `find_spec('redislite.async_falkordb_client')` or `find_spec('kuzu')`, else `bad`.
- **LLM_PROVIDER** (L180-195): read from `.env` only, default `claude-cli`.
  - claude-cli/codex-cli need the CLI on PATH.
  - `openai|kimi|minimax|deepseek|qwen|glm` need `LLM_API_KEY` that is not empty and not a placeholder (`your_api_key`,
    `your_api_key_here`).
  - Anything else warns.
- **DEERFLOW_MODEL** (L197-221): default `claude`.
  - claude: ok if `~/.claude/.credentials.json` exists or the `claude` CLI is present.
  - codex: `~/.codex/auth.json` or the CLI.
  - minimax/deepseek/qwen/glm/kimi: check the mapped key env in `.env`.
  - Anything else (including `antigravity`) → `warn` "Unknown".
- **Deep probes** (L236-505), only with `--deep` and only if the backend venv exists:
  - Preferred path (present on this checkout): `$BE_PY backend/scripts/preflight.py --deep --json [--pull]`. The
    JSONL output is converted to `level<TAB>message` by an inline python program (L259-266, 273-276) and routed:
    ok→`ok`, bad→`bad`, other→`dwarn`.
  - Fallback inline heredoc probe (L285-495), used only if `preflight.py` is absent. It:
    - imports `app.config.Config`;
    - live-tests OpenAI-compat providers (`validate_safe_url` SSRF guard, `openai` SDK, timeout 25, `max_tokens 16`,
      kimi UA header, `_DISABLE_THINKING_EXTRA_BODY`; 401/403/404/429 hints);
    - checks CLI presence for cli providers;
    - checks DEERFLOW_MODEL keys/base/model from `PROVIDER_META` or `_KEY_ENV_FALLBACK`;
    - checks the HF cache for `GRAPHITI_EMBED_MODEL` (default `paraphrase-multilingual-MiniLM-L12-v2`), with optional
      `SentenceTransformer` pull;
    - checks free disk on `GRAPHITI_DATA_DIR` and `UPLOAD_FOLDER` (<2 GB bad, <5 GB warn).
  - If zero lines are rendered → `bad` "deep probes produced no output" (L501-503).
- **Summary** (L507-518): FAILURES>0 → exit 1. DEEP_WARNINGS>0 → exit 2. Else exit 0 ("All checks passed").

### 4. `scripts/smoke.sh` — offline inter-stage contract smoke

`set -u` (smoke.sh:38).

**Env** (L57-66): `SIM_SEED` default 1337 (exported) and `LLM_TEMPERATURE_OVERRIDE` default 0 (exported).
`SMOKE_GRAPH` and `SMOKE_FULL` default 0 (exported). `SMOKE_TMP=$(mktemp -d ${TMPDIR:-/tmp}/daf_smoke.XXXXXX)`.
`PIPELINE_DATA_DIR` defaults to `$SMOKE_TMP/pipelines`. `trap cleanup EXIT INT TERM` runs `rm -rf $SMOKE_TMP`.

**Interpreter** (L69-87): prefers `backend/.venv/bin/python`. Else, if uv is available, a sentinel `uv-run`
(`uv run python`). Else exit 1. `run_py` always runs with cwd=`backend/`.

**Driver** (L96-472): written to `$SMOKE_TMP/_smoke_driver.py`.
- `sys.path.insert(0, cwd)` (L115). `_fail` prints `[smoke] STAGE FAILED (stage)` and raises SystemExit(3) (L118-120).
- `_StubLLM` (L123-154): `chat` returns `""`. `chat_json` returns `STUB_ONTOLOGY` when the prompt contains
  `知识图谱本体设计专家` (the ontology system prompt at ontology_generator.py:35,190) or contains both entity_types
  and edge_types; otherwise it returns `{}`. `supports_native_tools`=False.
- Fixtures: `STUB_ONTOLOGY` (4 entity types incl. the Person/Organization fallbacks, 2 edge types, L159-183),
  6 `FIXTURE_CHUNKS` (L186-193), `STUB_GRAPH_SNAPSHOT` (5 nodes and 2 edges in the `get_graph_data` shape, L197-231).
  Required key sets: `NODE_KEYS`/`EDGE_KEYS` (L233-236).

**Stages:**
- **Stage 2 `stage_ontology`** (L239-258): `OntologyGenerator(llm_client=_StubLLM(...)).generate(document_texts=[...],
  simulation_requirement=...)`. The result must be a dict with non-empty `entity_types`/`edge_types` and must contain
  Person and Organization.
- **Stage 3 `stage_graph`** (L286-310):
  - If `SMOKE_GRAPH=1`, `_build_real_graph` (L261-283) runs `GraphBuilderService().create_graph → set_ontology →
    add_text_batches(batch_size=5) → _wait_for_episodes → get_graph_data`. Any exception or 0 nodes → stub fallback.
    This uses a real LLM through the configured provider.
  - It asserts the top-level keys, non-empty nodes and edges, and node[0]/edge[0] key sets.
- **Stage 4 `stage_entities`** (L313-347): real graph → `ZepEntityReader().filter_defined_entities(graph_id,
  enrich_with_edges=True)`. Stub → re-implements the "label other than Entity/Node" filter itself. Asserts
  `FilteredEntities.to_dict()` keys, `filtered_count>0` and entity[0] keys.
- **Stage 5 `stage_sim_config`** (L350-427):
  - Truncates to 2 entities.
  - Builds `SimulationConfigGenerator` with `__new__`, bypassing `__init__` (which would build a real `LLMClient`,
    simulation_config_generator.py:435-453), and sets provider/api_key/base_url/model_name/llm=_StubLLM by hand.
  - `generate_config(...)` must return `SimulationParameters`, whose dict has
    `simulation_id, project_id, graph_id, time_config, agent_configs, event_config` and non-empty agent_configs.
  - Writes OASIS profiles through private `OasisProfileGenerator._save_twitter_csv` / `_save_reddit_json`
    (oasis_profile_generator.py:3062,3150). Asserts the CSV header ⊇ {user_id,name,username} and the reddit JSON[0] ⊇
    {user_id,username,name,bio,persona}.
  - Writes `simulation_config.json` into a **separate** `tempfile.mkdtemp(prefix="daf_smoke_stage_")` dir (L424-427, 458).
- **Stage 6 `stage_report`** (L430-454): builds a local `ReportOutline` with 3 `ReportSection`s. Asserts `to_dict`
  title and sections, and `to_markdown` ≥40 chars. It does not invoke ReportAgent.
- **`main`** (L457-467): runs all stages and prints `SMOKE_CONFIG=<path>` for the shell.

**Shell run** (L477-495): driver stdout and stderr go to `$SMOKE_TMP/driver.out`. On success it pretty-prints the
`[smoke] stage … OK` lines and extracts `SMOKE_CONFIG`. On failure it dumps the output and exits 1.

**Micro-sim** (L500-536), only with `SMOKE_FULL=1`:
`[g]timeout 120 python scripts/run_parallel_simulation.py --config $SMOKE_CONFIG --max-rounds 1 --no-wait`
(flags exist: run_parallel_simulation.py:5781-5816). rc 0 → ok. rc 124 → warn. Other → warn plus the last 12 lines.
**Never fails the smoke.**

**Exit 0** (L538-540).

### 5. `scripts/setup_port80.sh` — macOS-only pf redirect :80 → Flask

`set -euo pipefail` (L20).

**Constants** (L22-28): tag `drf-port80`, anchor `/etc/pf.anchors/drf.port80`, `/etc/pf.conf`,
LaunchDaemon `/Library/LaunchDaemons/com.drf.pf-port80.plist`, Apache `system/org.apache.httpd`.
`TARGET_PORT=${DRF_PORT:-5001}`.

- `status()` (L30-41): reports whether Apache is loaded, whether the tagged lines are in pf.conf, whether the anchor
  and daemon files exist, curls `127.0.0.1:$PORT/` and greps `<title>` from `http://localhost/`.
- `uninstall()` (L43-59): backs up pf.conf, `sed -i ''` deletes the tagged lines, `pfctl -f`, removes the anchor,
  boots out and removes the daemon, and re-enables and bootstraps Apache.
- **Root required** for every mode (L61-64). Args: `--status`, `--uninstall`, none = install. Anything else → exit 1
  (L66-71).

**Install** (L73-131):
1. Stop and disable Apache.
2. Write the anchor `rdr pass on lo0 inet proto tcp from any to any port 80 -> 127.0.0.1 port $PORT`.
3. If the tag is absent: back up pf.conf, insert `rdr-anchor "drf.port80" # drf-port80` after Apple's
   `rdr-anchor "com.apple/*"`, and append `load anchor … # drf-port80`.
4. Validate with `pfctl -nf`. On failure, restore the latest backup and exit 1.
5. `pfctl -f` and `pfctl -E`.
6. Write a RunAtLoad LaunchDaemon (`/sbin/pfctl -f /etc/pf.conf && /sbin/pfctl -E`), then bootout and bootstrap it.
7. Verify that `curl http://localhost/` contains "DeepResearchForecast", else print diagnostics. It always exits 0
   after the install step.

### 6. `init.sh` — harness smoke

`set -euo pipefail`. It:
- `test -f backend/pyproject.toml`;
- `test -x backend/.venv/bin/python`;
- `test -f frontend/package.json`;
- `test -f deerflow_bridge/deerflow_research.py` (init.sh:6-9);
- runs `python -m compileall -q` over 9 backend modules (actor_context, actor_dossier_compactor, actor_role_prompt,
  oasis_profile_generator, pipeline_orchestrator, simulation_config_generator, simulation_manager,
  simulation_runner, utils/actors) plus deerflow_bridge/deerflow_research.py (init.sh:11-21);
- runs `node -e` to assert frontend/package.json has a `scripts` key (init.sh:23-24);
- prints "DeepResearchForecast actor-grounding smoke check passed." (init.sh:26).

All targets exist on disk.

### 7. `package.json` (root)

Name `deepagentforecast` v0.2.0, license AGPL-3.0 (package.json:2-4, 27). The only devDependency is
`concurrently ^9.1.2` (L21-23). `engines.node >=20.19.0` (L24-26).

Scripts (L5-20):

| Script | Command |
|---|---|
| `setup` | root `npm install` plus `frontend npm install` |
| `setup:backend` | `cd backend && uv sync --python 3.12` |
| `setup:all` | `setup` then `setup:backend` |
| `doctor` | doctor.sh |
| `smoke` | smoke.sh |
| `dev` | `concurrently --kill-others -n backend,frontend "npm run backend" "npm run frontend"` |
| `start` | start.sh |
| `stop` | `start.sh --stop` |
| `backend` | `cd backend && uv run python run.py` (uv run syncs the project env first; start.sh instead calls `.venv/bin/python` directly) |
| `frontend` | `cd frontend && npm run dev` (frontend `dev`=`vite`, frontend/package.json:7) |
| `build` | frontend `vite build` |
| `test` | `cd backend && uv run pytest` |
| `lint` | `cd backend && uv run ruff check app` |
| `check:env` | `uv run python scripts/check_env_drift.py --strict` |

### 8. `backend/pyproject.toml`

- Project `mirofish-backend` 0.1.0, `requires-python >=3.12` (L2-7). The Chinese comment says to raise to 3.12 for
  falkordblite/redis and mentions "markers below", but there are none (L4-5).
- Runtime deps (L13-52):

| Group | Packages |
|---|---|
| Web | flask≥3.0, flask-cors≥6.0 |
| LLM | openai≥1.0, h2≥4.1 (for `LLM_HTTP2`) |
| Graph | **graphiti-core==0.29.2**, falkordblite≥0.5.0, redis<8, sentence-transformers≥3.0 |
| Simulation | **camel-oasis==0.2.5**, **camel-ai==0.2.78** |
| Files | PyMuPDF≥1.24, charset-normalizer≥3, chardet≥5 |
| Charts | plotly≥5.18, kaleido≥1.3, matplotlib≥3.7 (the comment says they must be declared or `uv sync` uninstalls them) |
| Utilities | python-dotenv≥1, pydantic≥2 |

- `[project.optional-dependencies].dev`: pytest≥8, pytest-asyncio≥0.23, pipreqs (L54-59). `[dependency-groups].dev`
  repeats pytest and pytest-asyncio without pipreqs (L72-76).
- `[tool.uv] override-dependencies = ["neo4j==5.23.0"]` resolves camel-oasis's neo4j pin against graphiti-core's
  neo4j≥5.26 (L61-66).
- Build backend hatchling, wheel packages `["app"]` (L68-79).
- pytest: `testpaths=["tests"]`, `addopts="-q"`, ignore DeprecationWarning (L83-86).
- ruff: line-length 120, py312, `select F,E9,B,C4`, `ignore F401,F841,B008` (L90-97).

### 9. `backend/requirements.txt` (legacy pip list)

The header says "Python 3.11+" and `pip install -r` (L4-5). It lists:
- flask and flask-cors;
- openai;
- **zep-cloud==3.13.0** (L17);
- camel-oasis==0.2.5 and camel-ai==0.2.78;
- PyMuPDF, charset-normalizer, chardet, python-dotenv, pydantic;
- matplotlib;
- **mcp≥1.10.0** (L46), plotly, kaleido;
- **networkx≥3.2** (L56).

It has none of graphiti-core, falkordblite, redis, sentence-transformers or h2. No script in this slice consumes it.

### 10. `.github/workflows/ci.yml`

Triggers: push to `main` and every `pull_request` (L5-8). All jobs run on `ubuntu-latest` with no caching and no
secrets:

1. **lint-and-drift** (L11-21):
   - `actions/checkout@v4` and `astral-sh/setup-uv@v5`;
   - `uvx ruff check --select F,E9 --ignore F401,F841,F541 backend/app backend/scripts deerflow_bridge`;
   - `python3 backend/scripts/check_env_drift.py --strict`. It uses the runner's system python, which works because
     the checker is stdlib-only and regex-parses config.py (check_env_drift.py:31-37, 54, 103-109).
2. **unit** (L23-38): `uv python install 3.12`, `uv venv --python 3.12`, `uv pip install pytest python-dotenv`, then
   `cd backend && uv run pytest -q`.
3. **byte-compile** (L40-50): `actions/setup-python@v5` 3.12, then
   `python -m compileall -q backend/app backend/scripts deerflow_bridge`.

### 11. `.env.example` (structure only)

- 707 lines, mostly Chinese comments. Exactly 3 active assignments: `LLM_PROVIDER=claude-cli` (L10),
  `RESEARCH_SOURCE_DENY_DOMAINS=economicsummarizer.com,insights.triplegains.com` (L346) and
  `RESEARCH_ALLOW_LOW_QUALITY_SOURCES=false` (L347).
- About 516 distinct commented-out `KEY=` names.
- Section banners (`# ===== … =====`):

| Line | Section |
|---|---|
| L1 | LLM provider (claude-cli default, codex-cli, openai, kimi, minimax, deepseek, qwen, glm) |
| L12/20/31/43/53/62 | Per-provider blocks (`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL_NAME` repeated 6×, plus the DeerFlow mirror keys `KIMI_API_KEY`, `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `ZHIPUAI_API_KEY`, `LLM_USER_AGENT`, `LLM_MINIMAX_DISABLE_THINKING`) |
| L70 | Local Graphiti graph (`GRAPH_BACKEND`, `GRAPHITI_*`, `FALKORDB_HOST/PORT`, `ZEP_*` retry knobs) |
| L91 | Chunking (`DEFAULT_CHUNK_SIZE=2500`, `DEFAULT_CHUNK_OVERLAP=250`) |
| L95 | Flask (`FLASK_DEBUG/HOST/PORT`) |
| L102 | `LLM_BOOST_*` |
| L108 | `OASIS_CLI_SEMAPHORE`/`OASIS_SEMAPHORE` |
| L113 | DeerFlow (`DEERFLOW_DIR/PYTHON/MODEL/RESEARCH_DEPTH/…`, `RESEARCH_ENGINE=v3`, `RESEARCH_LINEAR_*` v3 knobs L143-169) |
| L171 | EXECPLAN structured contracts (graph/sim/report) |
| L230 | EXECPLAN2 (security/API token/CORS, telemetry, cache, budgets, structured forecast, viz, PDF, ledger, seeds, calibration) |
| L291 | 2nd wave (tiered routing, fallback provider, adaptive context, retrieval/ontology/persona, research gates) |
| L369 | 3rd wave (fan-out, parallel tracks, budgets, search/fetch backends `SERPER/TAVILY/EXA/FIRECRAWL_API_KEY`, graph resolve, sim dynamics) |
| L450 | Polymarket |
| L490 | Ops-script knobs |
| L500 | R2 audit fixes (orchestration heartbeats, LLM client breakers, research RES-*, sim RUN-*, report RPT-*, bilingual, PM-2, RQ-2) |
| L620 | MCP server knobs (`DRF_MCP_*`; read only by app/mcp servers) |
| L628 | Wave 9 |
| L706 | Internal/test (`DRF_TEST_PROCESS`) |

### 12. `feature_list.json`

A 12-entry array of `{id, category, description, steps[], passes}`:
- `passes:true`: `feature_actor_intelligence_grounding_v2` (L3-19) and `feature_research_engine_v3` (L162-174).
- `passes:false`: `feature_localhost_drf_entry` (L21-33; requires "exactly one browser tab" and no duplicate
  `POST /api/research/run`), `feature_usage_lineage_truth`, `feature_live_budget_and_health`,
  `feature_shared_handoff_api_authority`, `feature_polymarket_provenance_history`, `feature_forecast_visual_quality`,
  `feature_graph_timeout_efficiency`, `feature_research_marginal_yield`, `feature_report_ensemble_efficiency` and
  `feature_controlled_optimization_validation` (the last needs a separately authorized paid run, L149-161).

No code reads this file. A grep of backend, deerflow_bridge and scripts `*.py` finds no reference.

### 13. `backend/CLAUDE.md`

It is a 10-line `<claude-mem-context>` auto-generated activity stub ("Backend restarted loading three improvement
commits", Jun 23 2026) (backend/CLAUDE.md:1-11). It is **gitignored** (`**/CLAUDE.md`, .gitignore:96-97) and contains
no backend guidance.

---

## Control flow

```
Fresh machine
  ./setup.sh ─┬─ prereq warnings (L81-146)
              ├─ provider pick → .env upserts (L151-383) → optional curl key test (L389-424)
              ├─ npm run setup  (L446-447 → package.json:6)
              ├─ cd backend && uv sync --python 3.12 (L471)
              ├─ deer-flow acquire: cp -R deer-flow-2.0.0 | git clone+pin (L520-569) → trim (L556-566)
              ├─ overlay: copy bridge modules/patches (L578-653) → python3 runtime_skill_sync.py (L632-640)
              │           → python3 apply_subagent/lead_agent/model_factory overlays (L659-699) → config.yaml if absent (L704-712)
              └─ deer-flow venv uv sync (L720-721) → [SETUP_DRF2=1: mcp into backend venv] → next steps
  npm run doctor  → doctor.sh (offline) [--deep → backend/scripts/preflight.py --deep --json]
  npm run smoke   → smoke.sh → temp driver in backend/ cwd → app.services.* (stub LLM) [SMOKE_FULL → run_parallel_simulation.py]
  npm start       → start.sh → (validate) → watcher --once preflight → _prepare_backend → _prepare_frontend
                     → _wait_ready ×2 → ownership re-verify → open browser → [attached: tail -F + watcher + monitor loop]
  npm stop        → start.sh --stop → _stop_from_pidfile backend, frontend
  npm run dev     → concurrently(uv run python run.py, vite) --kill-others
CI (push main / PR) → lint-and-drift ‖ unit ‖ byte-compile (independent jobs)
```

- Order inside start.sh is strictly backend before frontend (start.sh:512-518). The waits are sequential
  (L522-525).
- `start.sh` launches `backend/run.py`, which calls `Config.validate()` and exits 1 on errors before Flask starts
  (backend/run.py:27-33). That surfaces as "process exited before application readiness" (start.sh:345-347).
- In follow mode the progress watcher polls `backend/uploads/pipelines/*/pipeline_state.json` every 1 s
  (watch_pipeline_progress.py:131-150, 161, 179-182). On the initial poll it emits only active pipelines
  (`pending|running|processing|resuming`, L15, 143-145). Under `--once` (the start.sh preflight) it emits everything
  and exits 0 (L175-178).

---

## Data & artifacts

| Path | Writer / reader | Format / key content | Anchor |
|---|---|---|---|
| `.env` (repo root) | setup.sh creates and upserts; doctor.sh greps; backend `load_dotenv(override=True)` | `KEY=VALUE` lines. Keys written by setup: `LLM_PROVIDER`, `DEERFLOW_MODEL`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_API_KEY`, `<PROVIDER>_API_KEY` | setup.sh:280-383; doctor.sh:77-81; backend/app/config.py:18-24 |
| `.env.XXXXXX` temp | setup.sh `upsert_env` (then `mv`) | rewritten env | setup.sh:307-321 |
| `${TMPDIR:-/tmp}/setup_llm_test.XXXXXX` | setup.sh key test (0600, deleted) | provider HTTP response body | setup.sh:400-422 |
| `deer-flow/` (gitignored) | setup.sh assembles | trimmed DeerFlow tree plus `deerflow_research.py`, 7 bridge modules, model/middleware patches, `skills/public`, `config.yaml`, `backend/.venv` | setup.sh:519-736; .gitignore:84 |
| `backend/.venv` | `uv sync --python 3.12` | Python 3.12 env | setup.sh:471; package.json:7 |
| `.backend.pid` / `.frontend.pid` | start.sh writes `$!`; `--stop` reads and removes | a single PID line (the frontend PID is the npm process) | start.sh:32-33, 367, 379, 291; .gitignore:57-58 |
| `logs/backend.out.log` / `logs/frontend.out.log` | start.sh (nohup stdout+stderr, truncated by `>` on each launch, touched by `: >>`) | raw service output | start.sh:39-40, 366, 378, 507-508 |
| `backend/uploads/pipelines/*/pipeline_state.json` | read by watcher via start.sh | JSON `pipeline_id`, `status`, `error`, `stages{name:{status,progress,message,error}}` | start.sh:38, 503, 591; watch_pipeline_progress.py:52-57, 133 |
| `$TMPDIR/daf_smoke.XXXXXX/` | smoke.sh (deleted on exit) | `_smoke_driver.py`, `driver.out`, `sim.out` | smoke.sh:63-66, 96, 478, 513 |
| `$TMPDIR/daf_smoke_stage_*/` | smoke driver (**not deleted**) | `twitter_profiles.csv`, `reddit_profiles.json`, `simulation_config.json` | smoke.sh:404-427, 458 |
| `/etc/pf.anchors/drf.port80`, `/etc/pf.conf` (+ `.drf-port80-backup-<ts>`), `/Library/LaunchDaemons/com.drf.pf-port80.plist` | setup_port80.sh | pf rdr rule; tagged lines; RunAtLoad plist | setup_port80.sh:23-26, 46, 79-88, 100-116 |
| `deer-flow` venv `deer-flow/backend/.venv` | setup.sh uv sync | Python 3.12 env | setup.sh:720-721 |

In-memory structures:
- start.sh flags `BACKEND_MANAGED/STARTED`, `FRONTEND_MANAGED/STARTED` (L384-387).
- Restart counters (L574-575).
- `*_UNHEALTHY_SINCE` epoch seconds (L619-620).
- doctor counters `FAILURES/WARNINGS/DEEP_WARNINGS` (L61-63).
- setup's provider arrays (L156-187).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `FLASK_PORT` | 5001 | start.sh backend port and health URL (process env only; validated 1..65535) | start.sh:41, 487-490 |
| `START_BACKEND_TIMEOUT_SECONDS` | 60 | readiness wait iterations, backend | start.sh:45 |
| `START_FRONTEND_TIMEOUT_SECONDS` | 30 | readiness wait iterations, frontend | start.sh:46 |
| `START_HEALTH_CURL_TIMEOUT_SECONDS` | 2 | curl `--max-time` per probe | start.sh:47 |
| `START_HEALTH_FAILURE_GRACE_SECONDS` | 8 | attached-mode unhealthy grace before exit 1 | start.sh:48, 675 |
| `START_MONITOR_INTERVAL_SECONDS` | 1 | monitor loop sleep (positive finite float) | start.sh:49, 491-495, 698 |
| `START_FOLLOWER_RESTART_LIMIT` | 1 | max restarts of tail follower / watcher | start.sh:50, 626, 638 |
| `DEERFLOW_DIR` | `$ROOT/deer-flow` | setup install target; doctor check location (env > .env > default) | setup.sh:500; doctor.sh:138-139 |
| `DEERFLOW_VENDOR_DIR` | `$ROOT/deer-flow-2.0.0` | preferred engine seed | setup.sh:501 |
| `DEERFLOW_REPO` / `DEERFLOW_REF` | bytedance/deer-flow / `799bef6d…` (`main` = no pin) | clone fallback and pin | setup.sh:502-503, 534 |
| `DEERFLOW_PYTHON` | `deer-flow/backend/.venv/bin/python` | doctor's DeerFlow interpreter (env > .env) | doctor.sh:146-147 |
| `SETUP_NONINTERACTIVE` | 0 | `1` skips the picker | setup.sh:232 |
| `SETUP_DRF2` | 0 | `1` installs `mcp` for DRF-2 preview | setup.sh:750 |
| `LLM_PROVIDER` (in .env) | `claude-cli` | doctor check branch; setup picker default | doctor.sh:180; setup.sh:207-222 |
| `DEERFLOW_MODEL` (in .env) | `claude` | doctor credential check | doctor.sh:197 |
| `GRAPH_BACKEND` (in .env) | `auto` | doctor message only | doctor.sh:171 |
| `DOCTOR_DEEP_PULL`, `DOCTOR_BACKEND_DIR` | set by doctor | inline deep-probe fallback inputs | doctor.sh:286, 299, 311 |
| `SIM_SEED` | 1337 (smoke export) | Config.SIM_SEED (but `.env` overrides; see Surprises) | smoke.sh:57; config.py:296 |
| `LLM_TEMPERATURE_OVERRIDE` | 0 | exported; **no reader** in backend/app, backend/scripts or deerflow_bridge | smoke.sh:58 |
| `SMOKE_GRAPH` | 0 | `1` → real Graphiti graph leg | smoke.sh:59, 288 |
| `SMOKE_FULL` | 0 | `1` → OASIS micro-sim leg | smoke.sh:60, 500 |
| `PIPELINE_DATA_DIR` | `$SMOKE_TMP/pipelines` | exported; **no env reader** (Config uses fixed path) | smoke.sh:64; config.py:1581 |
| `TMPDIR` | `/tmp` | temp roots for smoke/setup | smoke.sh:63; setup.sh:400 |
| `DRF_PORT` | 5001 | pf redirect target port | setup_port80.sh:28 |
| `FRONTEND_HOST` (vite, out of slice) | `127.0.0.1` | Vite bind; port fixed 3000 `strictPort`, `open: true`, `/api` proxy → `localhost:5001` | frontend/vite.config.js:13-31 |

The `.env.example` knob catalog (about 516 names) belongs to the config slice. Here only the section structure is
mapped (see Walkthrough §11).

---

## External calls

| Target | Kind | Where | Notes |
|---|---|---|---|
| `{provider base}/chat/completions` | HTTPS LLM (1 token) | setup.sh:402-411 | only when a key was typed interactively; 25 s timeout |
| `https://github.com/bytedance/deer-flow.git` | git clone/fetch | setup.sh:532-537 | only when no vendor dir and no existing checkout |
| npm registry | `npm install` ×2 | setup.sh:446-453; package.json:6 | |
| PyPI / uv index | `uv sync` backend and deer-flow, `uv pip install` mcp | setup.sh:471, 720-721, 769-770 | |
| `python3 runtime_skill_sync.py`, `apply_*_overlays.py` | subprocess (system python3) | setup.sh:632-634, 664, 682, 694 | stdlib-only helpers |
| `backend/.venv/bin/python run.py` | detached subprocess | start.sh:366 | |
| `npm run dev` (→ `vite`) | detached subprocess | start.sh:378 | Vite itself also opens a browser (`open: true`, vite.config.js:22) |
| `http://localhost:$FLASK_PORT/health`, `http://localhost:3000/` | curl | start.sh:311, 332 | |
| `scripts/watch_pipeline_progress.py` | subprocess (`--once` preflight + background) | start.sh:503, 591 | |
| `tail -F`, `lsof`, `ps`, `kill`, `open`/`xdg-open` | process tools | start.sh:586, 111-116, 148, 235-270, 556-557 | |
| `backend/scripts/check_env_drift.py` | subprocess | doctor.sh:115, 126; ci.yml:21; package.json:19 | |
| `backend/scripts/preflight.py --deep --json` | subprocess (network: live keys, HF download with `--pull`) | doctor.sh:273-276 | |
| OpenAI SDK, `huggingface_hub`, `sentence_transformers` | inline deep fallback (dead on this checkout) | doctor.sh:331-349, 414, 443-444 | |
| `app.services.*` (stub LLM; real LLM if `SMOKE_GRAPH=1`) | in-process import from temp driver | smoke.sh:240, 269-275, 315-321, 352-355, 432 | |
| `backend/scripts/run_parallel_simulation.py` | subprocess, `[g]timeout 120` | smoke.sh:510-521 | needs a live LLM |
| `launchctl`, `apachectl`, `pfctl`, `curl localhost` | system admin (sudo) | setup_port80.sh:32-131 | |
| GitHub Actions: `actions/checkout@v4`, `astral-sh/setup-uv@v5`, `actions/setup-python@v5`, `uvx ruff` | CI | ci.yml:15-50 | |

---

## Cross-module edges

**Callers into this slice:**
- `package.json` scripts call every shell entrypoint: doctor, smoke, start, stop and check:env (package.json:9-19).
  setup.sh calls `npm run setup` (setup.sh:447).
- backend/tests/test_start_script_progress.py copies start.sh into a fixture and runs it (L38-47, 141). Its tests
  cover wrong-backend-on-port, generic-frontend-on-port, recycled-PID refusal, watcher crash restart and external
  health monitoring (L232-287). `test_vite_dev_server_uses_strict_port` is at L227.
- backend/tests/test_deerflow_bridge_sync_guard.py:213-235 parses setup.sh's bridge copy loop and asserts it deploys
  every module in the orchestrator's `_DEPLOYED_BRIDGE_MODULES`.
- backend/tests/test_drf2_skills_config.py:634-640 asserts setup.sh uses `runtime_skill_sync.py` with the exact
  `--source-root` / `--deployed-public-root` args.
- backend/tests/test_claude_prompt_cache.py:416-457 asserts the deployed `patches/models` and `patches/middlewares`
  match their sources byte for byte. It notes that models are deployed only by setup.sh.
- backend/scripts/preflight.py:486-498 is the canonical `--deep --json` JSONL producer that doctor.sh consumes.
- README.md:128-129, 1253-1277 and DRF_ARCHITECTURE.md:1706-1720 document these scripts.

**This slice calls out to:**
- `backend/run.py`, which calls `Config.validate` and `app.run(host=FLASK_HOST or 127.0.0.1, port=FLASK_PORT or 5001)`
  (backend/run.py:27-57).
- `backend/app/__init__.py:217-219` (`/health`).
- `frontend/index.html:7-11` (signature).
- `scripts/watch_pipeline_progress.py`.
- `backend/scripts/check_env_drift.py` and `backend/scripts/preflight.py`.
- `deerflow_bridge/{runtime_skill_sync.py, patches/apply_*_overlays.py, config.yaml, *.py modules}`.
- `app.services.{ontology_generator, graph_builder, zep_entity_reader, simulation_config_generator,
  oasis_profile_generator, report_agent}` (smoke driver).
- `backend/scripts/run_parallel_simulation.py` (smoke micro-sim).

**Runtime twin of setup's overlay:** `backend/app/services/pipeline_orchestrator.py:1441`
`_sync_deerflow_bridge_if_stale` re-syncs the following before each research launch:
- `deerflow_research.py` (L1462-1463);
- the 6 bridge modules (L1359-1362);
- `runtime_skill_sync.py` (L1520);
- middlewares (L1541-1551);
- `extensions_config.json`, which setup.sh never deploys (L1556-1578);
- the three overlays (L1600, 1642, 1669).

It also checks config.yaml drift (L1718-1726). It does **not** sync `patches/models`.

---

## Invariants, gates, validation

1. **start.sh signals only verified processes.** No signal is sent unless the PID's cwd equals the role directory,
   its command matches the role pattern and its process tree owns the role's listening port. This is re-checked
   immediately before TERM and before KILL (start.sh:210-233, 262-272).
2. **No launch over a foreign listener.** If a port is occupied and fails the app signature, start.sh refuses to
   launch (start.sh:417-420, 454-457).
3. **App-specific readiness, not just an open port.** The backend needs `{"status":"ok","service":"MiroFish Backend"}`.
   The frontend needs the DeepResearchForecast title, meta tag and `#app` (start.sh:309-336).
4. **Startup failure rolls back only what this run started** (start.sh:463-470, 542-547).
5. **Watcher preflight before any launch** in follow mode (start.sh:503-506).
6. **Numeric knob validation** happens before any side effect: exit 2 (start.sh:479-495).
7. **doctor default path makes no network calls and spends nothing.** Network probes require `--deep`, and model
   download requires `--deep --pull` (doctor.sh:11-26, 236).
8. **doctor exit-code contract** is 0, 1 or 2; an unknown option is 64 (doctor.sh:28-29, 50, 508-518).
9. **smoke default is offline and costs nothing.** Heavy legs need explicit `SMOKE_GRAPH=1` / `SMOKE_FULL=1`. A stage
   contract break exits 1 (the driver raises SystemExit(3)) (smoke.sh:22-36, 118-120, 492-494).
10. **setup never overwrites `.env` or `deer-flow/config.yaml`.** It upserts only specific keys (setup.sh:283-284,
    704-712, 327-383).
11. **Required overlays fail closed in setup.** Skill sync and the subagent and lead-agent overlays `exit 1`; the
    model-factory overlay is optional (setup.sh:628-640, 660-687, 693-699).
12. **CI gates:**
    - ruff pyflakes plus syntax errors;
    - every `os.environ.get/[...]` name in `backend/app/config.py` must appear in `.env.example`, minus an ignore set
      (check_env_drift.py:44-51, 103-109, 321-323);
    - backend pytest;
    - compileall.
13. **Python pin.** pyproject requires ≥3.12. setup and npm pass `--python 3.12` (pyproject.toml:7; setup.sh:471;
    package.json:7).

---

## Failure modes & recovery

| Failure | Symptom | Recovery | Anchor |
|---|---|---|---|
| backend venv missing | start.sh "backend Python is unavailable … run setup first", exit 1 | `./setup.sh` or `cd backend && uv sync --python 3.12` | start.sh:475-478 |
| `Config.validate()` error (bad LLM_PROVIDER, missing key, bad GRAPH_BACKEND/DEERFLOW_MODEL, semaphore<1) | run.py exits 1 and start.sh reports "exited before application readiness" | fix `.env`; read `logs/backend.out.log` | backend/run.py:27-33; config.py:1595-1640; start.sh:345-347 |
| port occupied by another app | "occupied by a wrong or unhealthy responder; refusing to launch" | free the port | start.sh:417-420, 454-457 |
| stale or recycled PID file | file removed without signalling | automatic | start.sh:404-411, 441-448 |
| verified PID not owning the port | refuses stop and launch; PID file kept | manual inspection | start.sh:215-218, 401-403 |
| readiness timeout | tail of both logs, rollback, exit 1 | inspect logs | start.sh:542-547, 357 |
| attached-mode crash or hang of a service | exit 1 after grace; **services left running** | `npm stop` and restart | start.sh:648-696 |
| watcher or tail died | restarted up to the limit, then exit 1 | rerun `npm start` (services already up are reused) | start.sh:623-646 |
| Ctrl-C in attached mode | followers killed, exit 130, services kept | `npm stop` when done | start.sh:604-614 |
| DeerFlow clone pin fetch fails | warning; stays on the default branch | `DEERFLOW_REF=main` or vendor dir | setup.sh:536-543 |
| skill sync or required overlay failure | setup exits 1 mid-run (deps already installed) | fix the drift, re-run setup | setup.sh:628-640, 660-687 |
| uv/npm failure | warning; setup continues | re-run the printed command | setup.sh:454-459, 474-476, 724-727 |
| pf.conf fails validation | backup restored, exit 1 | inspect `/etc/pf.conf` | setup_port80.sh:90-95 |
| doctor deep child crashes | ✗ "deep probes produced no output" | run the printed preflight command | doctor.sh:501-503 |
| smoke real-graph leg unavailable | automatic fallback to the stub snapshot | n/a | smoke.sh:276-283 |
| smoke micro-sim timeout or failure | warning only | n/a | smoke.sh:524-531 |

---

## Surprises

Doc-vs-code drift, dead code, gotchas. "suspected" marks issues not verified by execution.

1. **Two browser tabs on `npm start` (suspected).** start.sh opens `http://localhost:3000` (start.sh:554-560), and
   Vite is configured with `open: true` (frontend/vite.config.js:22), while frontend `dev` is plain `vite`
   (frontend/package.json:7). `--no-open` suppresses only start.sh's open. This matches the open ledger item
   `feature_localhost_drf_entry` ("exactly one browser tab", passes:false, feature_list.json:21-33).
2. **`FLASK_PORT` split brain (suspected).** start.sh reads `FLASK_PORT` only from its own environment
   (start.sh:41). run.py reads `os.environ['FLASK_PORT']` after `app.config` has run `load_dotenv(.env,
   override=True)` (backend/run.py:21-22,48; config.py:20-21). A `FLASK_PORT` set only in `.env` therefore moves the
   backend while start.sh health-checks 5001. The Vite proxy is also hard-coded to `localhost:5001`
   (vite.config.js:25).
3. **`load_dotenv(override=True)` beats shell exports.** smoke.sh's `SIM_SEED=1337` (smoke.sh:57) is silently
   replaced if `.env` sets `SIM_SEED`, because the driver imports `app.config` (config.py:20-21).
4. **Inert smoke exports.** `PIPELINE_DATA_DIR` (smoke.sh:64) is never read from the env.
   `Config.PIPELINE_DATA_DIR` is a fixed path (config.py:1581), and the only other mention is a comment
   (config.py:278). `LLM_TEMPERATURE_OVERRIDE` (smoke.sh:58) has no reader anywhere in backend/app, backend/scripts
   or deerflow_bridge. The header's "honored by the stages that read them" (smoke.sh:32-34) is therefore untrue for
   these two.
5. **smoke leaks a temp dir.** The driver's `tempfile.mkdtemp(prefix="daf_smoke_stage_")` (smoke.sh:458) is outside
   `$SMOKE_TMP` and is never removed by `cleanup` (smoke.sh:65-66). It contains profiles and simulation_config.json.
6. **smoke minor issues.** `SIM_DIR` is assigned and unused (smoke.sh:505). `set -e 2>/dev/null || true` switches on
   errexit mid-script in a script that started with only `set -u` (smoke.sh:38, 523).
7. **smoke stages 4 and 6 are weak checks.** The stub path of stage 4 re-implements the label filter instead of calling
   the reader (smoke.sh:322-335). Stage 6 constructs a `ReportOutline` locally and never touches ReportAgent
   generation (smoke.sh:430-454). Stage 5 depends on private methods `_save_twitter_csv`/`_save_reddit_json` and on
   `__new__` bypassing `__init__` (smoke.sh:360-365, 403-407).
8. **doctor `antigravity` gap.** Config accepts `DEERFLOW_MODEL=antigravity` (config.py:1544), and `.env.example:119`
   lists it. doctor.sh's case statement (doctor.sh:205-221) warns "Unknown DEERFLOW_MODEL", and setup.sh never offers
   it.
9. **doctor's inline deep fallback is dead code here.** `backend/scripts/preflight.py` exists, so L285-495 never runs.
   The comments "its cross-file part is not yet landed" (doctor.sh:233-234, 279-280) are stale.
10. **doctor cosmetic bug.** `${WARNINGS:+ ($WARNINGS warning(s))}` always expands because `WARNINGS` is "0", not empty,
    so a clean run prints "(0 warning(s))" (doctor.sh:516).
11. **doctor `envval` differs from python-dotenv.**
    - It uses the **first** active line (doctor.sh:79 `head -n1`), whereas dotenv keeps the last duplicate.
    - It deletes every `"` but not single quotes.
    - It ignores `export KEY=` lines.
    - `LLM_PROVIDER`, `DEERFLOW_MODEL` and `GRAPH_BACKEND` are read only from `.env`, while `DEERFLOW_DIR` and
      `DEERFLOW_PYTHON` honor the process env first (doctor.sh:138, 146, 171, 180, 197).
    - setup.sh's provider read (setup.sh:209, 324-325) uses `tr -d '[:space:]'`, so an inline comment glues onto the
      value (e.g. `minimax#comment`).
12. **Node 22.0–22.11 accepted.** The version predicate passes any major ≥22 (doctor.sh:87; setup.sh:95), although
    the comments and README say Vite 7 needs ^20.19 or ≥22.12 (setup.sh:89; README.md:1197).
13. **setup.sh header drift.** It says "node>=18" and "never hard-fails" (setup.sh:7-8), but the code requires ≥20.19
    and has four `exit 1` paths (setup.sh:630, 639, 662/668, 680/686). `python3` missing is only a warning (L126-132)
    but later becomes fatal for skill sync (L628-631). README.md:1220 says setup checks "Python 3.12", but setup only
    checks that some `python3` exists.
14. **"7 provider stanzas" message** (setup.sh:707) versus 8 model entries in deerflow_bridge/config.yaml:45-251 (adds
    `antigravity`). The comment at L701 lists 6.
15. **setup key-test exit-code concatenation (suspected).** `HTTP_CODE="$(curl … -w '%{http_code}' … || printf '000')"`
    (setup.sh:402-411). On a connection failure curl already writes `000` for `-w`, so the fallback appends a second
    `000`, giving `000000`. That falls into the generic "Provider returned HTTP 000000" branch instead of the
    "offline?" branch (L416-420). The test also always uses the table defaults for base URL and model, even when the
    user keeps a customized `.env` base or model (L345-354 vs L403, 407).
16. **`cp -R` into an existing empty `deer-flow/` nests the tree (suspected).** The acquire guard runs whenever
    `.git` and `backend/` are both absent (setup.sh:520), which includes an empty pre-existing directory. BSD and GNU
    `cp -R src existing_dir` create `existing_dir/deer-flow-2.0.0/`, so the overlay and venv steps then skip with
    "deer-flow not available".
17. **Model patches deploy only through setup.sh.** The runtime drift guard syncs middlewares and overlays but not
    `patches/models` (pipeline_orchestrator.py:1536-1551; test_claude_prompt_cache.py:417-419). Edits to
    `claude_provider.py`, `credential_loader.py` or `patched_minimax.py` therefore need a re-run of `./setup.sh`.
    Conversely, setup.sh never deploys `extensions_config.json`; only the orchestrator renders it
    (pipeline_orchestrator.py:1556-1578).
18. **`requirements.txt` is stale and divergent.**
    - It says "Python 3.11+" while pyproject requires ≥3.12.
    - It pins `zep-cloud==3.13.0`, although the graph layer is a local Graphiti shim that only mentions `zep_cloud` in
      docstrings (graphiti_client/__init__.py:3-7).
    - It omits graphiti-core, falkordblite, redis, sentence-transformers and h2 (requirements.txt:4, 17 vs
      pyproject.toml:7, 22-31).
    - Nothing in the slice installs from it.
19. **Undeclared direct imports in pyproject.**
    - `networkx` is imported by graph_builder.py:901 and report_visualizer.py:168 (guarded), and `mcp` by
      app/mcp/kg_server.py:324. Neither is in pyproject.
    - Both are present only transitively: camel-ai requires `mcp>=1.3.0` and torch requires `networkx>=2.5.1`, per the
      installed metadata in backend/.venv.
    - `ruff` is not a dependency and not installed in backend/.venv, so `npm run lint` (`uv run ruff check app`,
      package.json:18) works only if ruff is on PATH. CI sidesteps this with `uvx` (ci.yml:19).
20. **pyproject cruft.** The dev deps are declared twice: `optional-dependencies.dev` includes pipreqs and
    `dependency-groups.dev` does not (pyproject.toml:54-59, 72-76). The comment refers to non-existent "markers below"
    (L4-5).
21. **`backend/uv.lock` is tracked but deleted in the working tree.** `git ls-files` lists it, while git status shows
    ` D backend/uv.lock` and the file is absent. A local `uv sync` therefore re-resolves unpinned, while CI on a fresh
    checkout uses the committed lock.
22. **CI unit-job comment versus behavior (suspected).**
    - It creates a root `.venv` and `uv pip install pytest python-dotenv` "only the light deps" (ci.yml:32-37). It then
      runs `cd backend && uv run pytest -q`, which syncs the backend **project** environment (full sim and graph stack
      plus the default `dev` group) rather than using that root venv. The light-deps step is effectively redundant.
    - The step name says "telemetry/security/atomic/dates golden tests", but `testpaths=["tests"]` runs the whole
      backend suite (pyproject.toml:84; 182 entries in backend/tests).
    - CI does not build or test the frontend (frontend has `test:unit`, frontend/package.json:9). It does not run
      smoke.sh, doctor.sh or init.sh, and it has no dependency caching.
23. **Three different ruff configurations.** CI uses `--select F,E9 --ignore F401,F841,F541` (ci.yml:19), pyproject
    uses `select F,E9,B,C4 ignore F401,F841,B008` (pyproject.toml:96-97), and `npm run lint` uses the pyproject config
    on `app` only (package.json:18).
24. **The env-drift checker scans only `backend/app/config.py`** (check_env_drift.py:39, 103-109). Env vars read
    elsewhere (deerflow_bridge, app/mcp, scripts) are outside the gate. `.env.example` also documents
    `RESEARCH_GLOBAL_MODEL_CONCURRENCY` twice (L379, L383) and `GRAPH_RESOLVE_ENTITIES` twice (L180, L421). Its Flask
    example `FLASK_HOST=0.0.0.0` (L99) contradicts the safer real default `127.0.0.1` (backend/run.py:47).
25. **Waits are counted in iterations, not seconds.** `_wait_ready` counts loop iterations, each a probe of up to
    `HEALTH_CURL_TIMEOUT` seconds plus `sleep 1`. The "within 60s" message can therefore correspond to about 180 s of
    wall time in the worst case (start.sh:338-358).
26. **`start.sh --help` prints lines 12-21 verbatim.** The output starts mid-sentence ("handoff.md 2026-07-02/07-03
    entries)…") and keeps the `#` prefixes (start.sh:61). doctor.sh strips them (doctor.sh:48).
27. **`setup_port80.sh` gotchas.**
    - It uses `DRF_PORT` rather than `FLASK_PORT`, and `sudo` usually resets the env (setup_port80.sh:28).
    - It redirects to Flask, not Vite, so its "serves the DeepResearchForecast UI" check passes only if `frontend/dist`
      is built. Otherwise Flask returns the JSON hint (backend/app/__init__.py:242-248).
    - If `/etc/pf.conf` lacks Apple's `rdr-anchor "com.apple/*"` line, the `sed` insert is a no-op but the
      `load anchor` line is still appended. The rule would load without being referenced (suspected) (L85-88).
    - It is macOS-only (`sed -i ''`, launchctl, pfctl).
28. **Naming drift.** package.json `deepagentforecast` (L2), the smoke, doctor and setup banners "DeepAgentForecast"
    (smoke.sh:3, 89; doctor.sh:3; setup.sh:3, 71), the pyproject project `mirofish-backend` "MiroFish" (pyproject.toml:2,
    6), and the health service string "MiroFish Backend" (backend/app/__init__.py:219), which start.sh depends on. The
    UI and repo are "DeepResearchForecast".
29. **`init.sh` is narrower than its role.** It only compiles 10 actor-grounding files and asserts package.json has
    `scripts`. It does not import, run tests or check deer-flow (init.sh:11-24).
30. **`backend/CLAUDE.md` is not documentation.** It is a gitignored claude-mem stub (backend/CLAUDE.md:1-11;
    .gitignore:96-97).
31. **DRF_ARCHITECTURE.md undersells start.sh.** It describes `--stop` as "kills via .backend.pid/.frontend.pid" and
    readiness as "polls /health" (DRF_ARCHITECTURE.md:1706-1710). The code also verifies identity, cwd and port
    ownership, checks app signatures and has the attached watcher and monitor mode.
