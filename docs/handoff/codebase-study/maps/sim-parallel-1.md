# sim-parallel-1 — run_parallel_simulation.py part 1

Slice: `backend/scripts/run_parallel_simulation.py` lines 1–2530 (the file has 6154 lines). Branch `main`, read in full from disk on 2026-10-11.

Anchor convention: `rps:N` means `backend/scripts/run_parallel_simulation.py:N`. Every other anchor is a path relative to the repo root. Third-party anchors point at the pinned packages installed in `backend/.venv/lib/python3.12/site-packages/` (`camel-oasis==0.2.5`, `camel-ai==0.2.78`; pins at `backend/pyproject.toml:34-35`).

Scope note. Part 1 holds the module bootstrap and most of the *helpers* that the two platform runners call: action whitelists and per-role action clipping, system-prompt injection (world brief, calendar vocabulary, canonical Reddit role messages plus attestation), the IPC interview server, config loading and seal checks, trace-table → `actions.jsonl` extraction, model creation, agent activation (the "who acts this round" sampler), affect dynamics, the calendar "world clock", LLM call/token telemetry, tool-argument normalisation, the self-like guard, and seed-follow injection.

These parts are **not** in the slice; they are only described here where needed to explain how slice functions are called:

- the round loops (`rps:5008` Twitter, `rps:5559` Reddit);
- the post-round reply step (`run_reaction_phase`, `rps:4559`; gate `SIM_REACTION_PHASE`, `rps:4124`);
- the engagement-like sampler (`inject_engagement_likes`, `rps:3977`; gate `SIM_ENGAGEMENT_SAMPLER`, `rps:3897`);
- in-band world evolution (`_InbandWorldEvolution`, `rps:3366`);
- checkpoints (`rps:3747-3851`);
- `run_twitter_simulation` (`rps:4692`), `run_reddit_simulation` (`rps:5228`) and `main` (`rps:5779`).

## Purpose & position in the pipeline

`run_parallel_simulation.py` is Stage 5 (RUN) of the pipeline. `SimulationRunner` launches it as a **detached child process**: `python run_parallel_simulation.py --config <sim_dir>/simulation_config.json [--config-seal <manifest sha>] [--max-rounds N] [--resume]`. The runner sets `cwd=sim_dir`, sends stdout and stderr to `<sim_dir>/simulation.log`, and passes `SIM_SEED` / `SIM_RESUME` only in the child's environment (`backend/app/services/simulation_runner.py:884-953`). The script builds two OASIS (camel-oasis) social environments, Twitter and Reddit, from the profiles and `simulation_config.json` that the prepare stage wrote. It runs both round loops concurrently in one asyncio event loop (`rps:5930-5936`). Each round it chooses which agents act, lets their LLMs pick tool-call actions, reads the actions back out of each platform's SQLite `trace` table and appends them to `<sim_dir>/<platform>/actions.jsonl`. The runner tails those files to drive progress (`ARCHITECTURE_MAP.md:280`).

When the loops finish, the environments are **left open**. The process becomes a file-mailbox IPC server (`ParallelIPCHandler`, `rps:840`), so the report agent can interview simulated agents against the post-simulation world. It stays up until a `close_env` command, an idle timeout, or SIGTERM/SIGINT (`rps:6029-6081`). Part 1 also writes the run's health and accounting side-files (`llm_health.json`, `sim_llm_telemetry.json`, `reddit_runtime_system_messages.json`). The runner and the orchestrator read those files later to grade simulation health and meter tokens (`backend/app/services/simulation_runner.py:2134-2145`, `backend/app/services/pipeline_orchestrator.py:10472`, `backend/app/services/pipeline_orchestrator.py:10049`).

## Walkthrough (source order)

### 0. Module docstring and Windows UTF-8 shim (`rps:1-65`)

- **Docstring (`rps:1-26`).** Describes dual-platform parallel simulation, wait-for-commands mode after completion, single and batch interviews over IPC, and remote close. Usage lines show `--config`, `--no-wait`, `--twitter-only` and `--reddit-only`. They omit `--config-seal`, `--max-rounds` and `--resume`, which `main` also accepts (`rps:5788-5825`). The listed log layout includes `run_state.json`, but this script never writes that file; `SimulationRunner` does.
- **Windows-only block (`rps:35-65`).** Runs only when `sys.platform == 'win32'`. It sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` (setdefault), reconfigures stdout and stderr to UTF-8 with `errors='replace'`, and monkey-patches `builtins.open` with `_utf8_open` (`rps:53-63`). The patch defaults text-mode `open()` calls with no encoding to `encoding='utf-8'`, because OASIS opens files without an encoding. It has no effect on macOS or Linux.
- **`TOKENIZERS_PARALLELISM` (`rps:70`).** `os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")` runs before any Hugging Face import (tag XRUN-14). It silences the "process just got forked" warning flood that used to bury the end of `simulation.log`. Covered by `backend/tests/test_audit_fixes_runloop.py:375`.

### 1. Imports, globals, sampling RNG (`rps:72-114`)

- **Stdlib imports (`rps:72-89`).** `warnings` (`rps:87`) and the module-level `multiprocessing` (`rps:78`) are never used. `shutil` is imported at module level and again inside `init_logging_for_simulation` (`rps:186`).
- **Globals (`rps:93-95`).**
  - `_shutdown_event` is created in `main` (`rps:5831`), checked at the top of every round (`rps:5010`, `rps:5561`) and by the wait loop (`rps:6056`), and set by the signal handler (`rps:6119-6120`).
  - `_cleanup_done` lets a second signal force an exit (`rps:6116-6126`).
  - `_VALIDATED_CONFIG_MANIFEST_SHA256` is set by `main` from the seal check (`rps:5844-5846`) and consumed by the Reddit attestation (`rps:5323`).
- **`_build_sampling_rng()` (`rps:102-111`).** Reads **only** `os.environ["SIM_SEED"]`.
  - Missing or blank: returns an unseeded `random.Random()`, i.e. non-deterministic.
  - An integer string: returns `random.Random(int)`.
  - Any other value: falls back silently to an unseeded RNG.
- **`_RNG = _build_sampling_rng()` (`rps:114`).** Runs at import time, *before* `.env` is loaded (`rps:125-135`) and before `app.config` is imported. The process-wide RNG is used by:
  - the weighted sampler (`rps:1747`);
  - the activation draw (`rps:1854`);
  - the reaction and engagement phases (`rps:5154`, `rps:5170`);
  - checkpoint capture and restore (`rps:3776-3799`).

### 2. Path setup, `.env`, logging hygiene (`rps:116-187`)

- **`sys.path` (`rps:118-122`).** Inserts `backend/scripts` (for `action_logger`) and `backend` (for `app.*`) at the front of `sys.path`.
- **Script-level `.env` load (`rps:125-135`).** `load_dotenv(<project_root>/.env)` with the default `override=False`, so values already in the environment (for example from the runner) win. If the root `.env` is missing, it tries `backend/.env`. It prints `已加载环境配置: <path>` to stdout.
  - Caution: the import of `app.utils.oasis_llm` at `rps:191` imports `app.config`, which runs `load_dotenv(project_root_env, override=True)` (`backend/app/config.py:18-24`). From that point on, `.env` values **override** any variable the runner injected, whenever `.env` also defines it. See Surprises.
- **`MaxTokensWarningFilter` (`rps:138-145`), installed on the root logger at `rps:149`.** Drops records whose message contains both `"max_tokens"` and `"Invalid or missing"`. camel emits that warning through the root logger (`logging.warning`, `backend/.venv/.../camel/types/unified_model_type.py:67`), so a root-logger filter does catch it.
- **`disable_oasis_logging()` (`rps:152-170`).** For loggers `social.agent`, `social.twitter`, `social.rec`, `oasis.env` and `table`: sets the level to CRITICAL, clears handlers, and sets `propagate=False`.
- **`init_logging_for_simulation(simulation_dir)` (`rps:173-187`).** Calls `disable_oasis_logging()` and then `shutil.rmtree(<sim_dir>/log, ignore_errors=True)`, which removes a legacy log directory. Called once from `main` (`rps:5855`).

### 3. Hard dependencies (`rps:190-207`)

- `from action_logger import SimulationLogManager, PlatformActionLogger` (`rps:190`). These are the JSONL writers, defined at `backend/scripts/action_logger.py:22`/`:134`. [verifier: anchors are in the opposite order — `PlatformActionLogger` (the `actions.jsonl` writer) is at `:22` and `SimulationLogManager` at `:134`; `SimulationLogManager` writes `simulation.log` through a `FileHandler` plus a console handler, not JSONL (`backend/scripts/action_logger.py:22`, `backend/scripts/action_logger.py:134-180`)]
- `from app.utils.oasis_llm import create_oasis_model, get_oasis_semaphore` (`rps:191`). This sits **outside** the try/except.
- `try: from camel.models import ModelFactory; from camel.types import ModelPlatformType; import oasis; from oasis import ActionType, LLMAction, ManualAction, generate_twitter_agent_graph, generate_reddit_agent_graph`. On `ImportError` it prints a Chinese error plus `pip install oasis-ai camel-ai` and calls `sys.exit(1)` (`rps:193-207`). `ModelFactory` and `ModelPlatformType` are never used in this file.

### 4. Platform action whitelists (`rps:210-241`)

- **`TWITTER_ACTIONS` (`rps:214-224`), 9 actions.** CREATE_POST, LIKE_POST, REPOST, FOLLOW, DO_NOTHING, QUOTE_POST, CREATE_COMMENT, SEARCH_POSTS, TREND. The T3.11 comment (`rps:211-213`) explains that CREATE_COMMENT, SEARCH_POSTS and TREND were added because camel-oasis 0.2.5 has platform-agnostic handlers for them.
- **`REDDIT_ACTIONS` (`rps:227-241`), 13 actions.** LIKE_POST, DISLIKE_POST, CREATE_POST, CREATE_COMMENT, LIKE_COMMENT, DISLIKE_COMMENT, SEARCH_POSTS, SEARCH_USER, TREND, REFRESH, DO_NOTHING, FOLLOW, MUTE.
- **INTERVIEW is deliberately excluded.** It is triggered only through `ManualAction` from the IPC handler (`rps:990-993`).
- **Where they are used.** They become the agents' tool sets through `available_actions=` in `generate_twitter_agent_graph` / `generate_reddit_agent_graph` (`rps:4745`, `rps:5280`). OASIS filters its full tool list down to these names when it constructs each `SocialAgent` (`backend/.venv/.../oasis/social_agent/agent.py:99-104`).

### 5. Per-role action affordances (EXECPLAN2 I-2-3) (`rps:244-533`)

**Design comment (`rps:244-265`).** Normally every agent on a platform shares one action list. With this feature on, each agent's camel tools are trimmed after the graph is built and before `env.reset()`, using the public `ChatAgent.remove_tools` API. A one-line behaviour hint is also appended to the agent's system prompt. The feature is **off by default** and best-effort: any failure skips that agent.

**Constants:**

- **`ROLE_ACTION_POLICY` (`rps:269-415`).** A whitelist keyed by lowercase `entity_type`, 17 keys:
  - `governmentagency` and `official`: post, comment, search posts, do nothing.
  - `mediaoutlet`: adds quote, repost and trend.
  - `journalist`: quote, repost, search user.
  - `university`, `ngo`, `company`, `organization`, `institution`, `group` and `community`: official-voice sets; `ngo` adds QUOTE, and `group`/`community` add LIKE.
  - `professor`, `expert` and `faculty`: post, comment, quote, search, like.
  - `publicfigure`: adds repost and follow. [verifier: compared with the professor/expert/faculty set it adds REPOST and FOLLOW but also drops SEARCH_POSTS; its list is CREATE_POST, CREATE_COMMENT, QUOTE_POST, REPOST, LIKE_POST, FOLLOW, DO_NOTHING (`rps:382-390`)]
  - `activist`: the most aggressive set, including FOLLOW and TREND.
  - `audience`: LIKE_POST, DISLIKE_POST, LIKE_COMMENT, REPOST, CREATE_COMMENT, DO_NOTHING, REFRESH. There is no CREATE_POST, but see the floor rule below.
- **`_ROLE_FULL_ACCESS = {"student","alumni","person"}` (`rps:420`).** These roles get the platform's full union, untrimmed.
- **`_ROLE_ACTION_DEFAULT` (`rps:423-429`).** The fallback for unknown roles: post, comment, like, search posts, do nothing.
- **`_ROLE_ACTION_FLOOR = {CREATE_POST, CREATE_COMMENT, DO_NOTHING}` (`rps:432-436`).** Always granted when the platform has the action.
- **`_ROLE_BEHAVIOR_HINT` (`rps:440-447`).** A Chinese `【行为习惯】…` sentence for `governmentagency`, `official`, `mediaoutlet`, `journalist`, `activist` and `audience` only.

**Functions:**

- **`_build_role_type_map(config)` (`rps:450-462`).** Builds `{agent_id: entity_type.strip().lower()}` from `config["agent_configs"]`. Rows missing `agent_id` or `entity_type` are skipped.
- **`_allowed_actions_for_role(entity_type, platform_union)` (`rps:465-479`).**
  - A full-access role returns `list(platform_union)`.
  - Otherwise: `allowed = (policy ∩ union) ∪ (FLOOR ∩ union)`, returned in the platform union's order, which keeps logs stable. The policy is `ROLE_ACTION_POLICY.get(role, _ROLE_ACTION_DEFAULT)`.
  - Consequence: Twitter never gets DISLIKE, LIKE_COMMENT, REFRESH or MUTE, and Reddit never gets QUOTE_POST or REPOST.
- **`_apply_role_action_profiles(agent_graph, config, platform_union, log_info)` (`rps:482-533`).**
  - Returns early if the graph is `None`, or if `get_agents()` raises (logged).
  - For each `(agent_id, agent)`, removes `union_tool_names - allowed_names`, restricted to names present in `agent._internal_tools`, by calling `agent.remove_tools(list)` (`rps:516-523`). Only social-action tools are touched.
  - Then appends the role hint through `_inject_behavior_hint`.
  - A per-agent exception is logged and skipped (`rps:529-531`).
  - Logs counts of restricted and hinted agents (`rps:533`).
  - Called only when `_role_action_profiles_enabled()` (`rps:4750-4754`, `rps:5285-5289`).
- **`_inject_behavior_hint(agent, hint) -> bool` (`rps:536-556`).** The shared, idempotent "append to the system prompt" primitive.
  - Reads `agent._original_system_message`. Returns `False` if it is missing or has no `.content`.
  - Returns `True` without changes if `hint` is already a substring (idempotent).
  - Otherwise builds `original.create_new_instance(content + "\n\n" + hint)` and assigns it to `_original_system_message`.
  - Recomputes `agent._system_message = agent._generate_system_message_for_output_language()`. camel appends an output-language sentence only when `_output_language` is set (`backend/.venv/.../camel/agents/chat_agent.py:1317-1338`).
  - Calls `agent.init_messages()`, which **resets memory** to the new system message. That is safe only before `env.reset()` / any step.
  - Any exception returns `False`.
- **`_replace_agent_system_message(agent, content)` (`rps:559-573`).** The fail-closed *replace* variant. It sets the original message to exactly `content`, regenerates it, and calls `init_messages()`. It then raises `ValueError` if `_original_system_message.content != content`, or if the effective `_system_message.content != content`. The second check means it fails if camel appended an output-language suffix.

### 6. Canonical Reddit system messages and attestation (`rps:576-697`)

Context: OASIS's Reddit template injects age, gender, MBTI and country (`backend/.venv/.../oasis/social_platform/config/user.py:79-96`). Current "actor-intelligence/v1" actors must carry only their sealed role prompt.

- **`_enforce_canonical_reddit_system_messages(agent_graph, profile_path)` (`rps:576-627`).**
  - Derives `<profile stem>_roles.json`, i.e. `reddit_profiles_roles.json`. If that file is absent it returns `[]`, which is the legacy no-op.
  - Otherwise calls `OasisProfileGenerator.validate_role_prompt_manifest(profile_path)` (`backend/app/services/oasis_profile_generator.py:2794`). It raises on schema, profile-sha or count mismatches.
  - Loads `reddit_profiles.json` and maps `agents = {int(id): agent}`.
  - For each role whose `contract.actor_intelligence_schema_version == ACTOR_INTELLIGENCE_SCHEMA_VERSION` (`"actor-intelligence/v1"`, `backend/app/utils/actors.py:190`):
    - requires `reddit_system_message_version == "canonical-reddit-system-message/v1"` (`backend/app/services/oasis_profile_generator.py:59`);
    - requires an int `profile_index` within range, and an agent present at that index;
    - composes `canonical_reddit_system_message(username, persona)` (`backend/app/services/oasis_profile_generator.py:62-85`);
    - checks its sha256 against `reddit_base_system_message_sha256`;
    - **replaces** the agent's system message through `_replace_agent_system_message`.
  - Every check failure raises `ValueError`. The call site (`rps:5294`) has **no try/except**, so the Reddit platform fails closed.
  - Returns rows `{profile_index, actor_id, base_system_message}`.
- **`_attest_canonical_reddit_system_messages(agent_graph, profile_path, config, runtime_rows, config_manifest_sha256)` (`rps:630-697`).** Runs after world-brief and calendar injection (`rps:5318-5324`, also not wrapped).
  - With no rows it returns and writes nothing.
  - Raises if `config_manifest_sha256` is empty (no validated seal).
  - For each row it recomputes the expected bytes: `base`, plus `"\n\n" + _world_brief_header(config) + "\n" + brief` when `_world_brief_enabled()` and `config.world_brief` is non-blank, plus `"\n\n" + _CALENDAR_ACTION_VOCAB_TEMPLATE.format(unit=…)` when `temporal_config.mode == "calendar"` and `unit` is non-empty.
  - Raises if the effective `_system_message.content != expected`, or if it contains `"years old, with an MBTI personality type"`.
  - Records `{profile_index, actor_id, composition[], system_message_sha256, system_message_chars}`.
  - Writes `<sim_dir>/reddit_runtime_system_messages.json` atomically (`app.utils.atomic.write_json_atomic`, `allow_nan=False`) with fields:
    - `schema_version: "reddit-runtime-system-messages/v1"`;
    - `simulation_config_manifest_sha256`;
    - `actor_role_manifest_sha256` (sha of the bytes of `reddit_profiles_roles.json`);
    - `actor_count`;
    - `messages[]`.
  - The orchestrator later compares this file against the seal (`backend/app/services/pipeline_orchestrator.py:10048-10052`).
- **Ordering in the Reddit runner (`rps:5285-5324`).** Role-action clipping (which may append a hint) runs first. The canonical replace then **removes that hint**, deliberately, per the comment at `rps:5291-5293`; the tool removals stay. World brief and calendar vocabulary follow, then the attestation. Twitter has no canonical replace or attestation, because OASIS's Twitter template carries no demographics (`backend/.venv/.../oasis/social_platform/config/user.py:50`).

### 7. Calendar vocabulary and world brief (`rps:700-793`)

- **`_CALENDAR_ACTION_VOCAB_TEMPLATE` (`rps:702-708`).** English text: "In this simulation each round is one calendar {unit}." It then maps CREATE_POST to a period communiqué, QUOTE/COMMENT to a strategic response, FOLLOW to an alliance, LIKE/REPOST to an endorsement, and DO_NOTHING to strategic patience.
- **`_inject_calendar_vocabulary(agent_graph, temporal_config, log_info)` (`rps:711-736`).** Takes `unit` from `temporal_config.unit`. If the unit is blank or the graph is `None`, it returns. Otherwise it calls `_inject_behavior_hint` on every agent, skips per-agent failures, and logs `injected/total`. Called only when `calendar` is true (`rps:4767-4771`, `rps:5309-5313`).
- **`_WORLD_BRIEF_HEADER` / `_WORLD_BRIEF_HEADER_EN` (`rps:739-740`).** `"# WORLD BRIEF（共同世界背景）"` and `"# WORLD BRIEF (shared world background)"`.
- **`_world_brief_header(config)` (`rps:743-746`).** Returns the English header iff `_sim_output_language(config) == "English"`. That function is outside the slice (`rps:4151-4164`): it uses `SIM_OUTPUT_LANGUAGE`, then `config.output_language`, then a CJK-versus-Latin character count over `simulation_requirement`. Injection and attestation must use the same header function.
- **`_inject_world_brief(agent_graph, world_brief, log_info, header=_WORLD_BRIEF_HEADER)` (`rps:749-776`).** Builds the block `header + "\n" + brief.strip()` and appends it to every agent through `_inject_behavior_hint`. A blank brief or a `None` graph is a no-op. Logs `injected/total` and the brief length.
- **`_world_brief_enabled()` (`rps:779-785`).** Returns `_flag_true("SIM_WORLD_BRIEF","true")`, i.e. default on (Config default at `backend/app/config.py:1409`).
- **`_role_action_profiles_enabled()` (`rps:788-793`).** Reads **only** `os.environ["SIM_ROLE_ACTION_PROFILES"]`, default `"false"`. There is no Config attribute, unlike `_cfg_flag` flags.

### 8. Flag helpers (`rps:796-811`)

- **`_cfg_flag(name, default) -> str` (`rps:796-807`).** Uses a non-blank `os.environ[name]` first (stripped). Otherwise it returns `str(getattr(app.config.Config, name, default))`, or `default` when the value is `None`. If importing `Config` fails, it returns `default`.
- **`_flag_true(name, default)` (`rps:810-811`).** True when `_cfg_flag(...).lower()` is in `("true","1","yes","on")`. Config bools stringify to `"True"`, which is accepted.

### 9. IPC server (`rps:814-1267`)

**Constants (`rps:815-820`):** `IPC_COMMANDS_DIR="ipc_commands"`, `IPC_RESPONSES_DIR="ipc_responses"`, `ENV_STATUS_FILE="env_status.json"`, `IPC_CANCEL_SUFFIX=".cancel"`. The cancel suffix matches the client protocol in `backend/app/services/simulation_ipc.py:26-27`/`:323-332`.

- **`_ipc_write_json(path, payload)` (`rps:823-831`).** Uses `write_json_atomic` (temp file `.tmp-*` plus `os.replace`, `backend/app/utils/atomic.py:37-44`). If that helper raises, it falls back to a plain `open('w')` + `json.dump`.
- **`CommandType` (`rps:833-837`).** Plain string constants `interview`, `batch_interview`, `close_env`. This duplicates the enum in `backend/app/services/simulation_ipc.py:117`.

**`ParallelIPCHandler` (`rps:840-1267`)**, constructed by `main` only in wait mode (`rps:6037-6043`):

- **`__init__` (`rps:847-870`).** Stores both envs and graphs, either of which may be `None`. Creates `<sim>/ipc_commands` and `<sim>/ipc_responses`. Sets `last_command_at = time.monotonic()`, the base for the idle timer.
- **`update_status(status)` (`rps:872-879`).** Atomically writes `env_status.json` as `{status, twitter_available, reddit_available, timestamp}`. `main` writes `"alive"` (`rps:6044`) and `"stopped"` (`rps:6081`). The client's `check_env_alive` tests `status == "alive"` (`backend/app/services/simulation_ipc.py:424-439`).
- **`poll_command()` (`rps:881-919`).** Lists `*.json` in `ipc_commands`, sorted by mtime ascending (oldest first). `.cancel` and `.tmp-*` names never match.
  - If `<id>.cancel` exists, it deletes the command and the marker and moves to the next file.
  - Otherwise it returns the first file that parses as JSON. JSON or OS errors skip the file **without deleting it**.
  - There is no `.processing` claim, unlike `SimulationIPCServer` (`backend/app/services/simulation_ipc.py:547`), which no script uses.
- **`send_response(command_id, status, result=None, error=None)` (`rps:921-957`).**
  - If `<id>.cancel` exists, or `<id>.json` no longer exists (client gave up), it deletes both, prints `客户端已放弃命令…`, and **writes no response**.
  - Otherwise it atomically writes `ipc_responses/<id>.json` as `{command_id, status, result, error, timestamp}`, then deletes the command and marker on a best-effort basis.
- **`_get_env_and_graph(platform)` (`rps:959-974`).** Returns `(env, graph, name)` for `"twitter"`/`"reddit"` when that env exists, else `(None, None, None)`.
- **`_interview_single_platform(agent_id, prompt, platform)` (`rps:976-1002`).**
  - With no env it returns `{"platform", "error": "<platform>平台不可用"}`.
  - Otherwise: `agent = graph.get_agent(agent_id)`, then `await env.step({agent: ManualAction(INTERVIEW, {"prompt": prompt})})`, then reads the answer back with `_get_interview_result`.
  - OASIS runs the interview under its LLM semaphore and records it in `trace` (`backend/.venv/.../oasis/environment/env.py:130-134`; `backend/.venv/.../oasis/social_platform/platform.py:1348-1388`).
  - An exception becomes `{"platform", "error": str(e)}`.
- **`handle_interview(command_id, agent_id, prompt, platform=None)` (`rps:1004-1073`).**
  - When `platform` is `"twitter"`/`"reddit"`: a single-platform interview. The response is `completed` with the result, or `failed` with the error.
  - Otherwise both available platforms are interviewed concurrently with `asyncio.gather` (`rps:1046-1058`). The result is `{agent_id, prompt, platforms: {name: result}}`, and it is `completed` if at least one platform succeeded. If none did, it is `failed` with the joined errors.
  - With no env at all it is `failed` with `没有可用的模拟环境`.
- **`handle_batch_interview(command_id, interviews, platform=None)` (`rps:1075-1174`).**
  - Groups each item by `item.platform` or the default; items with no platform go to both available platforms.
  - Builds **one** `env.step` per platform, keyed by agent object, so a duplicate agent_id keeps only its last prompt. `get_agent` failures only print a warning.
  - Afterwards it reads results for **every** requested item, including ones whose agent lookup failed, and stores them as `results["<platform>_<agent_id>"]`.
  - A platform-level exception prints and drops that platform's results (`rps:1135-1136`, `rps:1162-1163`).
  - `completed` with `{interviews_count, results}` if any result exists, else `failed` with `没有成功的采访`.
  - Items that explicitly target a platform whose env is `None` are dropped silently.
- **`_get_interview_result(agent_id, platform)` (`rps:1176-1217`).**
  - Opens `<sim>/<platform>_simulation.db` and runs `SELECT user_id, info, created_at FROM trace WHERE action='interview' AND user_id=? ORDER BY created_at DESC LIMIT 1`.
  - Returns `{agent_id, response: info.response | info, timestamp}`, with `response` set to the raw string if the JSON fails to parse.
  - A missing DB or any error leaves `response=None`; the error is printed.
- **`process_commands() -> bool` (`rps:1219-1267`).**
  - Polls one command. With none it returns `True`.
  - On a command it refreshes `last_command_at` (`rps:1231`) and dispatches.
  - INTERVIEW: uses `args.agent_id` (default **0**), `args.prompt` (default `""`) and `args.platform`.
  - BATCH_INTERVIEW: uses `args.interviews` and `args.platform`.
  - Both refresh the idle timer again after the call (`rps:1247`, `rps:1257`).
  - CLOSE_ENV sends `completed` (`{"message": "环境即将关闭"}`) and returns **False**, so the wait loop exits.
  - An unknown type gets a `failed` response and `True`.

### 10. Config loading and seal re-validation (`rps:1270-1345`)

- **`load_config(config_path, expected_sha256=None)` (`rps:1270-1282`).** Reads the **raw bytes**. If `expected_sha256` is given and `sha256(bytes) != expected`, it raises `ValueError("simulation config changed after seal validation")`. It decodes UTF-8 JSON and requires a dict.
- **`validate_direct_child_config_seal(config_path, expected_manifest_sha256=None)` (`rps:1285-1345`).** Revalidates the seal at the child-process boundary.
  - `simulation_dir = dirname(abspath(config_path))`. Loads `state.json` if it exists, using `simulation_config_manifest_sha256` and `simulation_config_sha256`.
  - Raises `"runner and prepared state disagree on config seal"` if both the CLI `--config-seal` and the state manifest sha are present and differ (`rps:1302-1307`).
  - **current_role_evidence** is true when `reddit_profiles_roles.json` or `twitter_profiles_roles.json` exists, is a dict, and has `role_contract_version != "actor-role/v1"` or a truthy `actor_context_required` (`rps:1309-1323`).
  - `require = bool(cli seal or state manifest sha or current_role_evidence or state.actor_context_count)` (`rps:1324-1329`).
  - Raises when current_role_evidence holds but the state lacks either fingerprint (`rps:1330-1333`).
  - Raises when `require` holds and the config basename is not `simulation_config.json` (`rps:1334-1335`).
  - Then delegates to `app.services.simulation_manager.validate_simulation_config_seal(sim_dir, expected_manifest_sha256=cli or state, expected_config_sha256=state, expected_simulation_id=state.simulation_id, require=require)` (`rps:1336-1345`). The delegate:
    - checks the manifest file sha, schema and simulation id;
    - checks that `simulation_config_file == "simulation_config.json"`;
    - checks the config's raw and canonical sha;
    - checks the cast/context bindings and the role-manifest bindings;
    - returns the manifest with `manifest_sha256` added;
    - returns `{}` when the manifest is absent and nothing is required (`backend/app/services/simulation_manager.py:137-221`).
  - `main` passes `manifest.simulation_config_sha256` on to `load_config` (`rps:5847-5850`).

### 11. Trace-table extraction to `actions.jsonl` (`rps:1348-1719`)

- **`FILTERED_ACTIONS = {'refresh','sign_up'}` (`rps:1349`).** These are never logged.
- **`ACTION_TYPE_MAP` (`rps:1352-1368`).** Lowercase DB action names to upper-case canonical names (15 entries, including `interview`). Unknown names fall back to `action.upper()` (`rps:1468`).
- **`get_agent_names_from_config(config)` (`rps:1371-1392`).** Returns `{agent_id: entity_name}` from `agent_configs`, defaulting to `Agent_<id>`. The runners add OASIS names for agents that are missing (`rps:4788-4790`).
- **`fetch_new_actions_from_db(db_path, last_rowid, agent_names) -> (actions, new_last_rowid)` (`rps:1395-1484`).**
  - Opens a fresh sqlite connection and runs `SELECT rowid, user_id, action, info FROM trace WHERE rowid > ? ORDER BY rowid`. The cursor is `rowid` because Twitter's `created_at` is an integer time step while Reddit's is a datetime string (`rps:1423-1424`).
  - For each row it advances `new_last_rowid` (including filtered rows) and skips filtered actions.
  - Parses `info` as JSON, using `{}` on failure.
  - Keeps **only** these keys: `content`, `post_id`, `comment_id`, `quoted_id`, `new_post_id`, `follow_id`, `query`, `like_id`, `dislike_id` (`rps:1447-1465`).
  - Maps the type, calls `_enrich_action_context`, and appends `{agent_id: user_id, agent_name, action_type, action_args}`.
  - A missing DB returns `([], last_rowid)`. Any exception prints `读取数据库动作失败` and returns what was collected so far.
  - Callers: the seed backlog drain (`rps:4918`), the scheduled-event drain (`rps:5046`), the main per-round read (`rps:5131`), the reply step (`rps:4649`) and the engagement sampler (`rps:4047`), plus the Reddit equivalents.
- **`_enrich_action_context(cursor, action_type, action_args, agent_names)` (`rps:1487-1592`).** Mutates `action_args` in place:
  - LIKE/DISLIKE_POST: adds `post_content` and `post_author_name` through `_get_post_info(post_id)`.
  - REPOST: `post.original_post_id` of `new_post_id`, giving `original_content` and `original_author_name`.
  - QUOTE_POST: `quoted_id` gives `original_*`, and `post.quote_content` of `new_post_id` gives `quote_content`.
  - FOLLOW: `follow.followee_id` by `follow_id`, giving `target_user_name`.
  - MUTE: `user_id`/`target_id` would give `target_user_name`. This branch is unreachable; see Surprises.
  - LIKE/DISLIKE_COMMENT: adds `comment_content` and `comment_author_name` through `_get_comment_info`.
  - CREATE_COMMENT: `post_id` would give `post_content` and `post_author_name`. This depends on a key OASIS does not record; see Surprises.
  - Exceptions are printed and swallowed.
- **`_get_post_info` (`rps:1595-1638`), `_get_user_name` (`rps:1641-1673`) and `_get_comment_info` (`rps:1676-1719`).** SQL joins of post/comment with `user`. Author names prefer `agent_names[user.agent_id]` and fall back to `user.name`, then `user.user_name`. They return `None` on error.

### 12. Model creation (`rps:1722-1735`)

- **`create_model(config, use_boost=False)`** delegates to `app.utils.oasis_llm.create_oasis_model`. Provider resolution order is `LLM_PROVIDER` env, then `config.llm_provider`, then `Config.LLM_PROVIDER`, then `'claude-cli'` (`backend/app/utils/oasis_llm.py:481-487`).
  - CLI providers (`claude-cli`, `codex-cli`) get a `CLIModel`.
  - `openai`/`kimi`/`minimax` and the rest use camel `ModelFactory`, wrapped in an empty-assistant guard and a 422/429 fallback guard (`backend/app/utils/oasis_llm.py:557-600`).
  - Twitter calls it with `use_boost=False` (`rps:4732`). Reddit uses `use_boost=True` (`rps:5268`), which picks `LLM_BOOST_*` only for API providers that have a boost key.

### 13. Activation sampler — who acts each round (`rps:1738-1875`)

- **`_weighted_sample_without_replacement(items, k)` (`rps:1738-1749`).** Efraimidis–Spirakis A-Res sampling.
  - Empty input or `k <= 0` returns `[]`. `k >= len` returns all ids in input order, unshuffled.
  - Otherwise the key is `_RNG.random() ** (1/max(1e-6, w))`; it sorts descending and takes the top k.
- **`_resolve_hour_multiplier(time_config, hour)` (`rps:1752-1769`).** First match wins:
  - `peak_hours` (default `[9,10,11,14,15,20,21,22]`) gives `peak_activity_multiplier` (1.5).
  - `off_peak_hours` (default `[0..5]`) gives 0.3.
  - `morning_hours` (default `[]`) gives 0.4.
  - `work_hours` (default `[]`) gives 0.7.
  - Anything else gives 1.0.
  - Covered by `backend/tests/test_audit_fixes_runloop.py:53-74`.
- **`_resolve_start_hour(time_config)` (`rps:1772-1782`).** `time_config.start_hour`, else `_cfg_flag("SIM_START_HOUR","0")`, then `int(float(x)) % 24`. Junk values give 0.
- **`_supported_log_kwargs(logger, method_name, fields)` (`rps:1785-1799`).** Filters the calendar extras `{period_start, period_end, period_label, calendar_unit}` (built at `rps:5022-5029`) down to the logger method's real parameters, dropping `None` values. With `**kwargs` the whole set passes through; empty fields or an introspection error give `{}`.
  - Current `PlatformActionLogger.log_round_start` accepts only `period_label`, and `log_round_end` only `period_end` (`backend/scripts/action_logger.py:68-100`).
- **`get_active_agents_for_round(env, config, current_hour, round_num, last_active_ids=None, calendar=False)` (`rps:1802-1875`).** Returns `[(agent_id, agent)]`. `round_num` is unused in the body.
  - `base_max = time_config.agents_per_hour_max` (default 20). `multiplier = 1.0` in calendar mode, else the hour multiplier.
  - Influence normalisation: `max_infl = max(influence_weight or 1.0)` (`rps:1833-1836`).
  - Per agent config (`rps:1840-1855`):
    - Calendar mode with `cadence == "principal"`: the agent joins `principal_ids` and skips sampling.
    - Hours mode: the agent is skipped if `current_hour ∉ active_hours`, default `range(8,23)`, i.e. hours 8–22.
    - `p = activity_level × (0.5 + 0.5·infl/max_infl) × multiplier`, times **1.5** if the agent was in `last_active_ids`.
    - The agent becomes a candidate if `_RNG.random() < min(1, p)`.
  - `target_count = max(1, int(min(3·base_max, max(base_max, ceil(N/5))) × multiplier))` (`rps:1858-1859`).
  - `selected = weighted_sample(candidates, target_count)`. Principals are **prepended**; they are uncapped and do not use the sampled quota (`rps:1862-1865`).
  - Each id is resolved through `env.agent_graph.get_agent`, and failures are dropped silently.
  - The callers set `last_active_ids` to this round's active ids, and keep it across dead rounds when `SIM_RECENCY_CARRY=true` (`rps:5054-5056`).

### 14. Agent affect dynamics hooks (EXECPLAN2 I-2-1) (`rps:1878-1937`)

- **`_build_dynamics_tracker(config, log_info)` (`rps:1886-1898`).** Returns `None` unless `Config.SIM_AGENT_DYNAMICS`, which **defaults to true** (`backend/app/config.py:1399`). It reads Config only, with no env-first lookup. Otherwise it returns `AgentDynamicsTracker.from_config(agent_configs, config_obj=Config)` (`backend/app/services/agent_dynamics.py:123-148`). Any exception logs and returns `None`.
- **`_inject_agent_dynamics(active_agents, tracker, log_info)` (`rps:1901-1925`).** For each active agent with a non-empty `tracker.state_line(aid)` (a Chinese `【你当前状态】…` line, `backend/app/services/agent_dynamics.py:193-210`), it calls `agent.update_memory(BaseMessage.make_user_message("StateUpdater", line), OpenAIBackendRole.SYSTEM)`. It runs before `env.step` (`rps:5079`). The camel context builder drops this SYSTEM record; see Surprises.
- **`_observe_agent_dynamics(tracker, actual_actions, name_to_id)` (`rps:1928-1937`).** Calls `extract_round_signals`, then `tracker.observe_round`, and swallows all errors. It runs after the reply step (`rps:5163`).

### 15. Calendar "world clock" injection (CAL-TEMPORAL) (`rps:1940-2020`)

- **`_inject_period_context(env, active_ids, round_num, period, timeline, fired_events, world_delta, response_step=False, language="")`.** Called only in calendar mode, before each round's `env.step` (`rps:5083-5094`). `timeline` is `temporal_config`, `fired_events` is `_scheduled_events_due(...)` and `world_delta` is the in-band evolution's latest summary.
  - Returns if `period` is not a non-empty dict, or if camel imports fail.
  - Header line: `# WORLD CLOCK — {label} ({period_start} → {period_end}) | round {r+1}/{n_rounds} | one {unit} per round | forecast horizon {horizon_date} ({max(0, n_rounds-(r+1))} periods remain)`.
  - Four fixed English lines frame each post as the actor's most consequential action that period.
  - With `response_step`, it adds a line saying a separate reply step follows.
  - With `language`, it adds "Write all of your posts and replies in {language}."
  - `## CONFIRMED EVENTS THIS PERIOD` lists event `content`, prefixed `[date] ` if not already bracketed, or `(none)`.
  - `## WHAT CHANGED LAST PERIOD` is added only when `SIM_WORLD_DELTA` is true (default true; `backend/app/config.py:1075`). Its body is the delta, or `(first period)`.
  - Writes the note with **`OpenAIBackendRole.USER`** (role_name `WorldClock`) to each active agent's memory. Per the docstring (`rps:1945-1949`), camel 0.2.78 drops every SYSTEM record after the first. Per-agent failures are skipped.

### 16. LLM health and token telemetry (RUN-2, DEFECT-3) (`rps:2023-2308`)

- **Globals (`rps:2047-2061`).**
  - `SIM_LLM_TELEMETRY_FILE="sim_llm_telemetry.json"` and `SIM_LLM_TELEMETRY_SCHEMA="sim-llm-telemetry/v1"`.
  - `_SIM_LLM_METER_RUN_TOKEN = uuid4().hex`, minted once per process at import; it is the orchestrator's idempotency key.
  - `_SIM_LLM_METER_STARTED = time.time()` and `_SIM_LLM_USAGE_LOCK` (a `threading.Lock`).
  - `_SIM_LLM_USAGE = {calls, errors, prompt_tokens, completion_tokens, by_source{}, by_model{}}`.
  - `_SIM_LLM_TELEMETRY_SINK = {"dir": None, "config": None}`, pinned by `main` (`rps:5840`, `rps:5851`).
- **`_record_sim_llm_usage(source, model, pt, ct)` (`rps:2064-2085`).** Thread-safe. It increments the totals and the `by_source[source]` and `by_model[model]` buckets. Negative or `None` values are clamped to 0, and it never raises.
- **`_record_sim_llm_error()` (`rps:2088-2094`).** Increments `errors`.
- **`_accumulate_sim_llm_response(response)` (`rps:2097-2120`).**
  - No `usage`: records `source="missing"` with 0 tokens.
  - A `response.id` starting with `chatcmpl-cli-`: `source="estimate"`. That is the length/4 estimate synthesized by `oasis_llm._build_chat_completion`, which the CLI bridge and the LLMClient fallback both use (`backend/app/utils/oasis_llm.py:149-210`).
  - Anything else: `source="provider"`.
- **`_wrap_llm_client_usage(client)` (`rps:2123-2176`).** Monkey-patches `client.chat` and `client.chat_json`. An exception increments errors and re-raises. On success it records `provider` usage from `client._last_usage` when that is non-zero, else an `estimate` via `_estimate_tokens_of(messages/result)`. Used for in-band world evolution (`rps:3446`) and the post-hoc decision channel (`rps:6005`). A wrapping failure returns the client unchanged.
- **`_write_sim_llm_telemetry(simulation_dir, config=None, log_info=None)` (`rps:2179-2228`).**
  - Deep-copies the usage under the lock and resolves the provider with `oasis_llm._resolve_provider`.
  - The model label is the `by_model` key with the most calls, else `config.llm_model`, else the provider.
  - Atomically writes `<sim>/sim_llm_telemetry.json` with `{schema_version, simulation_id (config or basename), meter_run_token, provider, model, calls, errors, prompt_tokens, completion_tokens, total_tokens, by_source, by_model, wall_s, written_at}`.
  - Never raises. Written after the loops (`rps:5952`) and again in `__main__`'s `finally` (`rps:6143-6147`).
  - Read by `PipelineOrchestrator._record_sim_run_telemetry` (`backend/app/services/pipeline_orchestrator.py:10472-10530`) and rotated by the runner (`backend/app/services/simulation_runner.py:1306`).
- **`_wrap_model_llm_counter(model) -> {"calls","errors"}` (`rps:2231-2267`).**
  - If the model has `_arequest_chat_completion`, **only** the async path is wrapped. CLIModel's async path delegates to the sync one, so wrapping both would double count.
  - Otherwise `_request_chat_completion` is wrapped.
  - Each call does `calls += 1`. An exception increments `errors`, calls `_record_sim_llm_error()` and re-raises. A success feeds `_accumulate_sim_llm_response`.
  - The wrap goes on top of `create_oasis_model`'s guards, so a call rescued by the LLMClient fallback counts as a success (estimate source).
  - A failure to wrap leaves zeros.
  - Covered by `backend/tests/test_audit_fixes_runloop.py:117-140`.
- **`_write_llm_health(simulation_dir, platform, counter, log_info)` (`rps:2270-2308`).**
  - `rate = errors/calls`, or 0 with no calls. `threshold = float(_cfg_flag("SIM_LLM_ERROR_RATE_THRESHOLD","0.5"))`, falling back to 0.5 on parse error.
  - Reads `<sim>/llm_health.json` if it exists, keeping it only if it has a dict `platforms`, and merges in `platforms[platform] = {llm_calls, llm_errors, error_rate (4 dp), degraded: calls>0 and rate>threshold}`, plus `threshold` and `updated_at`.
  - Writes atomically and logs a ⚠ line when degraded.
  - Called once per platform at the end of its loop (`rps:5205`, `rps:5756`). `SimulationRunner.write_run_summary` downgrades `ok` to `llm_degraded` (`backend/app/services/simulation_runner.py:2134-2145`).

### 17. Tool-argument normaliser (XRUN-14) (`rps:2311-2385`)

- **`_TOOL_ARG_ALIASES` (`rps:2318-2321`).** For `like_comment` and `dislike_comment` it maps a hallucinated `post_id` to `comment_id`.
- **`_normalize_tool_kwargs(kwargs, params, tool_name)` (`rps:2324-2338`).** A pure function.
  - Known parameters pass through.
  - An alias is renamed when its target is a real parameter not already supplied; this prints `[tool-args] … 已改名为`.
  - Any other unknown key is **dropped**, with a `[tool-args] … 丢弃未知参数` print to stdout.
- **`_wrap_agent_tool_arg_normalizer(agent_graph, log_info)` (`rps:2341-2385`).** Gated by `SIM_TOOL_ARG_NORMALIZE` (default true; `backend/app/config.py:587`).
  - For each agent's `_internal_tools` FunctionTool it skips tools already marked `_sim_arg_normalized`, tools whose signature is uninspectable, and tools with a `**kwargs` signature.
  - It wraps `tool.func` in a sync or async `functools.wraps` wrapper that filters kwargs, and sets `_sim_arg_normalized=True`.
  - Logs the count. Called after the prompt injections (`rps:4775`, `rps:5328`).

### 18. Self-endorsement guard (`rps:2388-2457`)

- **`_SELF_ENDORSE_QUERIES` (`rps:2391-2398`).**
  - `like_post` takes argument `post_id`, with SQL `SELECT u.agent_id FROM post p JOIN user u … WHERE p.post_id=?`.
  - `like_comment` takes argument `comment_id`, with the matching comment join.
- **`_target_author_agent_id(db_path, query, target_id)` (`rps:2401-2417`).** Returns `int(row[0])`, or `None` when the target id is not an int, the DB is missing, a sqlite error occurs, or there is no row.
- **`_wrap_agent_self_like_guard(agent_graph, db_path, log_info)` (`rps:2420-2457`).**
  - For each agent and each of `like_post`/`like_comment` present as an **async** tool that is not already marked: it wraps the func.
  - The wrapper takes the target from `kwargs[arg]`, or the first positional argument, and looks up the author. If the author agent id equals the wrapping agent's id, it returns `{"success": False, "error": "You cannot like your own post or comment."}` without executing. Otherwise it awaits the original.
  - Marks `_sim_self_like_guard=True` and logs the count.
  - Twitter has only `like_post` among these (TWITTER_ACTIONS has no LIKE_COMMENT). Reddit has both.
  - Applied after the normaliser (`rps:4780-4783`, `rps:5333-5336`), so the guard is the **outer** layer.

### 19. Seed follow edges (T3.3, ITEM 20) (`rps:2460-2528`)

- **`async inject_initial_follows(env, event_config, log_info, agent_names=None, action_logger=None) -> int`.** `agent_names` and `action_logger` are accepted but unused.
  - Reads `event_config.initial_follows`; empty means return 0.
  - For each `[follower, followee]` pair that coerces to ints and is not a self-follow: calls `env.agent_graph.add_edge(follower, followee)` best-effort for **all** pairs, which updates the in-memory social graph the recommender sees. It then queues the followee under its follower. [verifier: the in-memory `AgentGraph` is not read by the OASIS 0.2.5 platform. The recommender works from the DB `user`/`post`/`trace` tables (`backend/.venv/lib/python3.12/site-packages/oasis/social_platform/platform.py:329-376`). The Twitter refresh builds its in-network feed by joining the DB `follow` table (`platform.py:281-293`). Only the FOLLOW ManualActions that survive the cap therefore shape feeds, so the throttle shrinks the effective follow graph rather than only the log noise. The code comments claiming otherwise (`rps:2464`, `rps:2489-2491`) are inaccurate for OASIS 0.2.5]
  - Throttle: `cap = _max_follows_per_agent_round()`, i.e. `SIM_MAX_FOLLOWS_PER_AGENT_ROUND`, default 3 (`rps:3919-3924`; `backend/app/config.py:623`). If `cap > 0`, `agent_dynamics.throttle_seed_follows` truncates each follower's list to `cap` and reports the dropped count (`backend/app/services/agent_dynamics.py:310-332`). A throttle exception falls back to the uncapped lists.
  - Multi-pass injection: for `p in range(max list length)`, one `env.step` maps each follower that still has a p-th followee to `ManualAction(FOLLOW, {"followee_id": …})`, because one agent can take only one action per step. A per-pass failure is logged and the loop continues.
  - Returns the applied count.
  - Called once per platform when not resuming (`rps:4906-4910`). The runner then drains the FOLLOW trace rows and logs them as round 0 with `is_seed_action: True` (`rps:4917-4931`).

## Control flow

How part 1 is driven, end to end; part-2 call sites are anchored for orientation:

1. **Import time.**
   - Windows shim (`rps:35-65`); `TOKENIZERS_PARALLELISM` (`rps:70`).
   - `_RNG` built from the `SIM_SEED` env (`rps:114`).
   - `sys.path` setup and script-level `.env` load with no override (`rps:118-135`).
   - Root log filter (`rps:149`).
   - Import of `action_logger` and `app.utils.oasis_llm`, which imports `app.config` and re-runs `load_dotenv(override=True)` (`rps:190-191`; `backend/app/config.py:18-24`).
   - camel/oasis import, or `sys.exit(1)` (`rps:193-207`).
   - Telemetry globals and the run token (`rps:2047-2061`).
2. **`__main__` (`rps:6132-6154`).** `setup_signal_handlers()` (SIGTERM/SIGINT: the first sets `_shutdown_event`, the second calls `sys.exit(1)`), then `asyncio.run(main())`. The `finally` block writes the final `sim_llm_telemetry.json`. [verifier: the `except SystemExit: pass` around `asyncio.run` swallows that `sys.exit(1)`, so the forced exit ends with status 0. The same applies to the `sys.exit(1)` calls inside `main` (`rps:5835`, `rps:5876`, `rps:6126`, `rps:6138-6139`). The runner compensates by requiring `simulation_end` markers when the exit code is 0 (`backend/app/services/simulation_runner.py:1089-1099`)]
3. **`main()` (`rps:5779`).**
   - Parse args. Pin the telemetry dir.
   - **`validate_direct_child_config_seal`** (`rps:5841`), then **`load_config`** with the sealed sha (`rps:5847`).
   - `init_logging_for_simulation` (`rps:5855`). `SimulationLogManager` (`rps:5858`). Disk preflight. A soft agent-id alignment warning (`rps:5896-5906`).
   - Run both platforms with `asyncio.gather(..., return_exceptions=True)` and `semaphore_platforms=2` (`rps:5930-5943`), or one platform for `--twitter-only` / `--reddit-only`.
4. **Per-platform setup (Twitter `rps:4692-4990`, Reddit `rps:5228-5540`)**, in this order:
   1. `calendar = temporal_config.mode == "calendar"` (`rps:4726-4729`).
   2. `create_model` (`rps:4732`), then `_wrap_model_llm_counter` (`rps:4734`).
   3. `generate_*_agent_graph(profile, model, available_actions=TWITTER_ACTIONS|REDDIT_ACTIONS)`.
   4. If `SIM_ROLE_ACTION_PROFILES`: `_apply_role_action_profiles` (try/except).
   5. **Reddit only:** `_enforce_canonical_reddit_system_messages` (fail-closed).
   6. If `SIM_WORLD_BRIEF`: `_inject_world_brief` with `_world_brief_header(config)` (try/except).
   7. If calendar: `_inject_calendar_vocabulary` (try/except).
   8. **Reddit only:** `_attest_canonical_reddit_system_messages` (fail-closed).
   9. `_wrap_agent_tool_arg_normalizer`, then `_wrap_agent_self_like_guard` (each in try/except).
   10. `get_agent_names_from_config`.
   11. `oasis.make(...)`, then `env.reset()`.
   12. Initial posts (round 0), then `inject_initial_follows`, then `fetch_new_actions_from_db` to drain the seed backlog.
   13. `_build_dynamics_tracker` (`rps:4966`).
5. **Each round (`rps:5008-5193`).**
   - Shutdown check. Disk check (raises). Scheduled events fired, then a drain fetch.
   - **`get_active_agents_for_round`** (`rps:5050`). Recency set update. `log_round_start` with `_supported_log_kwargs`.
   - Dead round (no active agents): `log_round_end(0)`, in-band heartbeat, checkpoint, continue.
   - **`_inject_agent_dynamics`** (`rps:5079`). In calendar mode, **`_inject_period_context`** (`rps:5085`).
   - `env.step({agent: LLMAction()})`. Failures are counted toward the consecutive-failure breaker (`rps:5101-5128`).
   - **`fetch_new_actions_from_db`** (`rps:5131`), then log each action.
   - Reply step `run_reaction_phase` (`rps:5150-5160`).
   - **`_observe_agent_dynamics`** (`rps:5163`). Engagement likes (`rps:5167-5174`). In-band `deliver` (`rps:5179-5182`).
   - `log_round_end`, checkpoint.
6. **After the loop.** In-band `platform_done`. **`_write_llm_health`** (`rps:5205`). Dynamics summary file.
7. **Back in `main`.**
   - **`_write_sim_llm_telemetry`** (`rps:5952`).
   - Optional emergent metrics. In-band finalize. Optional post-hoc decision channel using **`_wrap_llm_client_usage(LLMClient())`** (`rps:6005`).
   - In wait mode: `ParallelIPCHandler(...)`, `update_status("alive")`, then a loop of `process_commands()` with a 0.5 s `wait_for(_shutdown_event)`. It exits on CLOSE_ENV, on idle beyond `SIM_IDLE_CLOSE_MIN` (default 60 min; `rps:6049-6066`), or on a signal.
   - Then `update_status("stopped")` and `env.close()` for each platform.

## Data & artifacts

| Artifact | Dir. | Writer/reader in slice | Format / key fields |
|---|---|---|---|
| `<sim>/simulation_config.json` | read | `load_config` `rps:1270` | Raw bytes hashed; JSON dict. Keys read in the slice: `agent_configs[].{agent_id, entity_name, entity_type, activity_level, influence_weight, active_hours, cadence}`, `time_config.{agents_per_hour_max, peak_hours, off_peak_hours, morning_hours, work_hours, *_activity_multiplier, start_hour}`, `temporal_config.{mode, unit, n_rounds, horizon_date}`, `world_brief`, `event_config.initial_follows`, `llm_model`, `simulation_id`, `output_language`, `simulation_requirement` |
| `<sim>/state.json` | read | `validate_direct_child_config_seal` `rps:1291-1301` | `simulation_config_manifest_sha256`, `simulation_config_sha256`, `simulation_id`, `actor_context_count` |
| `<sim>/{reddit,twitter}_profiles_roles.json` | read | `rps:1310-1323`, `rps:581`, `rps:678-680` | `role_contract_version`, `actor_context_required`, `roles[].{contract.actor_intelligence_schema_version, reddit_system_message_version, profile_index, actor_id, reddit_base_system_message_sha256}` |
| `<sim>/simulation_config_manifest.json` | read (delegate) | `backend/app/services/simulation_manager.py:146-221` | Schema, shas, bindings |
| `<sim>/reddit_profiles.json` | read | `rps:592-593` | List; `[i].username`, `[i].persona` |
| `<sim>/reddit_runtime_system_messages.json` | write | `rps:682-697` | `reddit-runtime-system-messages/v1` attestation |
| `<sim>/{twitter,reddit}_simulation.db` | read | `rps:1395-1484`, `rps:1176-1217`, `rps:2401-2417` | OASIS SQLite: `trace(rowid, user_id, action, info JSON, created_at)`, `post`, `comment`, `user(user_id, agent_id, name, user_name)`, `follow(follow_id, followee_id)` |
| `<sim>/ipc_commands/<uuid>.json` (+ `.cancel`) | read/delete | `rps:881-919`, `rps:928-957` | `{command_id, command_type, args}` |
| `<sim>/ipc_responses/<uuid>.json` | write | `rps:941-950` | `{command_id, status, result, error, timestamp}` |
| `<sim>/env_status.json` | write | `rps:872-879` | `{status: alive/stopped, twitter_available, reddit_available, timestamp}` |
| `<sim>/llm_health.json` | read+write | `rps:2270-2308` | `{platforms: {twitter/reddit: {llm_calls, llm_errors, error_rate, degraded}}, threshold, updated_at}` |
| `<sim>/sim_llm_telemetry.json` | write | `rps:2179-2228` | `sim-llm-telemetry/v1` |
| `<sim>/log/` | delete | `rps:184-187` | Legacy directory |
| `<sim>/<platform>/actions.jsonl` | write (through `PlatformActionLogger`, called from part 2) | Rows produced by `fetch_new_actions_from_db` | `{round, timestamp, agent_id, agent_name, action_type, action_args, result, success}` (`backend/scripts/action_logger.py:54-63`) |

Important in-memory structures:

- **`_RNG`** (`rps:114`): the only randomness source for activation and sampling.
- **`_SIM_LLM_USAGE`** (`rps:2052`): process-global across both platforms and both LLMClient wrappers.
- **`llm_counter`:** a per-platform dict returned by `_wrap_model_llm_counter`.
- **`ParallelIPCHandler.last_command_at`** (`rps:870`): the idle timer.
- **`agent_names`:** `{id: name}`. Its inverse `dyn_name_to_id` (`rps:4967`) feeds dynamics signals.

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `SIM_SEED` (env only) | unset, i.e. non-deterministic | Seeds `_RNG`. A non-int value falls back to non-deterministic. Read before `.env` is loaded | `rps:102-114` |
| `TOKENIZERS_PARALLELISM` | set to `false` if unset | Silences HF fork warnings | `rps:70` |
| `PYTHONUTF8`, `PYTHONIOENCODING` | setdefault on Windows only | UTF-8 I/O | `rps:38-39` |
| `SIM_ROLE_ACTION_PROFILES` (env only) | `false` | Per-role tool clipping plus behaviour hint | `rps:788-793` |
| `SIM_WORLD_BRIEF` | `true` (env, then Config) | World-brief injection; also part of the Reddit attestation | `rps:779-785`, `backend/app/config.py:1409` |
| `SIM_OUTPUT_LANGUAGE` | `""` | Chooses the EN/中文 world-brief header (through `_sim_output_language`) and the language line in the world clock | `rps:743-746`, `rps:4151-4164` |
| `SIM_WORLD_DELTA` | `true` | Adds the "WHAT CHANGED LAST PERIOD" section | `rps:2007`, `backend/app/config.py:1075` |
| `SIM_START_HOUR` | `0` (`time_config.start_hour` wins) | Start hour of the simulated day | `rps:1772-1782`, `backend/app/config.py:584` |
| `SIM_AGENT_DYNAMICS` (Config only) | `true` | Builds `AgentDynamicsTracker` | `rps:1886-1898`, `backend/app/config.py:1399` |
| `SIM_LLM_ERROR_RATE_THRESHOLD` | `0.5` | `degraded` cut-off (strict `>`) | `rps:2279`, `backend/app/config.py:589` |
| `SIM_TOOL_ARG_NORMALIZE` | `true` | Tool kwarg normaliser | `rps:2343`, `backend/app/config.py:587` |
| `SIM_MAX_FOLLOWS_PER_AGENT_ROUND` | `3` (`<=0` means unlimited) | Seed FOLLOW action cap per follower | `rps:2492`, `rps:3919-3924`, `backend/app/config.py:623` |
| `LLM_PROVIDER` / `config.llm_provider` | `claude-cli` | Model backend and telemetry provider label | `rps:1735`, `backend/app/utils/oasis_llm.py:481-487` |
| `LLM_BOOST_API_KEY/BASE_URL/MODEL_NAME` | unset | Reddit boost model (API providers only) | `rps:5268`, `backend/app/utils/oasis_llm.py:495-504` |
| `SIM_IDLE_CLOSE_MIN` (used by `main`) | `60` minutes | Idle auto-close of the IPC wait loop | `rps:6049-6052` |
| `time_config.*`, `temporal_config.*`, `agent_configs[].*` | see Data table | Activation math, calendar mode | `rps:1823-1859` |

## External calls

- **LLM (indirect).** Every agent action, interview and dynamics or clock-injected round goes through the camel model returned by `create_model` (`rps:1722-1735`). That is a CLI bridge (`claude`/`codex` subprocess, through `LLMClient`) or an OpenAI-compatible HTTP API (`backend/app/utils/oasis_llm.py:557-600`). Calls are counted at `rps:2231-2267`. Interviews run through `env.step` (`rps:995`, `rps:1128`, `rps:1155`).
- **LLMClient (indirect).** `_wrap_llm_client_usage` wraps instances whose `.chat`/`.chat_json` hit providers (`rps:2123-2176`); the callers are outside the slice.
- **SQLite (direct).**
  - `sqlite3.connect` on `<platform>_simulation.db`: trace extraction (`rps:1420`), interview readback (`rps:1190`) and the self-like author lookup (`rps:2410`).
  - The OASIS platform task owns its own connection to the same DB.
- **OASIS env.** `env.step(...)` for interviews (`rps:995`, `rps:1128`, `rps:1155`) and seed follows (`rps:2523`). `agent_graph.add_edge` (`rps:2484`). `agent_graph.get_agent/get_agents` throughout.
- **camel ChatAgent internals.** `remove_tools`, `_original_system_message`, `_generate_system_message_for_output_language`, `init_messages`, `update_memory`, `_internal_tools[*].func` (`rps:522`, `rps:544-553`, `rps:564-567`, `rps:1923`, `rps:2018`, `rps:2382`, `rps:2454`).
- **Filesystem.** IPC dirs and status files; atomic JSON writes through `app.utils.atomic.write_json_atomic` (`rps:682`, `rps:828`, `rps:2220`, `rps:2302`).
- **Subprocess.** None in the slice. The script itself is the subprocess, launched by `backend/app/services/simulation_runner.py:943-953`.

## Cross-module edges

**Who calls into this slice:**

- `SimulationRunner.start_simulation` spawns the script, adds `--config-seal` only for this script, and injects `SIM_SEED` / `SIM_RESUME` into the child env (`backend/app/services/simulation_runner.py:884-953`). `simulation_manager` prints manual run commands (`backend/app/services/simulation_manager.py:1533`, `:1542`). `api/simulation.py` lists the script as a known runner (`backend/app/api/simulation.py:1367-1378`).
- `SimulationIPCClient` (`backend/app/services/simulation_ipc.py:209-422`) is the file-mailbox client for `ParallelIPCHandler`, used by `report_agent`, `api/simulation` and `mcp/sim_server`.
- Tests import the module as `rps`:
  - `backend/tests/test_audit_fixes_runloop.py`: multiplier, start hour, LLM counter, health, normaliser, IPC cancel and orphan handling, fetch enrichment.
  - `backend/tests/test_sim_meter_persistence.py`: telemetry.
  - `backend/tests/test_oasis_v1_provenance.py`: canonical Reddit enforce/attest, calendar vocabulary, world brief.
  - `backend/tests/test_simulation_config_seal.py`: seal and `load_config`.
  - `backend/tests/test_sim_realism_item20.py`: follow throttle.
  - `backend/tests/test_calendar_round_loop.py`: principals and calendar activation.
  - `backend/tests/test_sim_reaction_phase.py`: period context and self-like guard.
  - `backend/tests/test_audit_fixes_runner.py`: RNG.

**What the slice calls out to:**

- `app.utils.oasis_llm.{create_oasis_model, get_oasis_semaphore, _estimate_tokens_of, _resolve_provider}` (`rps:191`, `rps:2132`, `rps:2189`).
- `app.services.simulation_manager.validate_simulation_config_seal` (`rps:1336`).
- `app.services.oasis_profile_generator.{CANONICAL_REDDIT_SYSTEM_MESSAGE_VERSION, OasisProfileGenerator.validate_role_prompt_manifest, canonical_reddit_system_message}` and `app.utils.actors.ACTOR_INTELLIGENCE_SCHEMA_VERSION` (`rps:584-589`).
- `app.services.agent_dynamics.{AgentDynamicsTracker, extract_round_signals, throttle_seed_follows}` (`rps:1892`, `rps:1933`, `rps:2495`).
- `app.utils.atomic.write_json_atomic`, `app.config.Config`, `action_logger`, camel and oasis.

**Artifact consumers downstream:**

- `llm_health.json` is read by `SimulationRunner.write_run_summary` (`backend/app/services/simulation_runner.py:2134-2145`).
- `sim_llm_telemetry.json` is read by `PipelineOrchestrator._record_sim_run_telemetry` (`backend/app/services/pipeline_orchestrator.py:10472`).
- `reddit_runtime_system_messages.json` is read by the orchestrator's run-reuse/seal check (`backend/app/services/pipeline_orchestrator.py:10048-10052`).
- `env_status.json` is read by `SimulationIPCClient.check_env_alive` (`backend/app/services/simulation_ipc.py:424-439`), and the runner force-writes `stopped` on child exit (`backend/app/services/simulation_runner.py:1570-1590`).

## Invariants, gates, validation

- **Seal chain (fail closed).**
  - The CLI seal must equal the state seal when both exist (`rps:1302-1307`).
  - Current-contract roles require state fingerprints (`rps:1330-1333`).
  - Required seals force the `simulation_config.json` filename (`rps:1334-1335`).
  - The bytes `load_config` executes must hash to the manifest's `simulation_config_sha256` (`rps:1277-1278`, `rps:5847-5850`).
  - The Reddit canonical messages must match their sealed base sha (`rps:619-620`).
  - The final effective message must equal the deterministic composition (`rps:663-666`).
  - The message must not contain the demographics phrase (`rps:667-668`).
  - The runtime must have a validated manifest sha (`rps:640-641`).
- **Role whitelist invariant.** A role is never granted an action outside the platform union, and always keeps CREATE_POST, CREATE_COMMENT and DO_NOTHING when the platform has them (`rps:476-479`). Only social-action tool names are removed (`rps:516-520`).
- **Prompt-injection ordering.** Everything that calls `init_messages()` (hint, brief, vocabulary, canonical replace) must run **before** `env.reset()` / any step, otherwise agent memory is wiped. The call sites honour this (`rps:4748-4771` before `rps:4811-4818`).
- **Trace cursor invariant.** `last_rowid` only grows. Filtered rows still advance it (`rps:1434`). The callers drain seed and scheduled-event rows before the first organic fetch, so they are not counted as organic (`rps:4912-4931`, `rps:5044-5046`).
- **Activation bounds.** `target_count >= 1` (`rps:1859`). Probabilities are capped at 1 (`rps:1854`). Principals are uncapped (`rps:1862-1865`).
- **IPC.** Responses are written atomically. No response is written for a cancelled or abandoned command (`rps:932-939`). Cancelled commands are deleted before they run (`rps:906-912`).
- **Telemetry never interferes.** Every telemetry and health helper swallows its own exceptions (`rps:2084`, `rps:2119`, `rps:2174`, `rps:2227`, `rps:2265`, `rps:2307`). Wrapped model and LLMClient calls re-raise the original exception after counting (`rps:2143-2144`, `rps:2243-2246`).
- **Idempotence.** Hints are skipped if already present (`rps:547-548`). Tool wrappers are marked `_sim_arg_normalized` / `_sim_self_like_guard` and not re-wrapped (`rps:2358`, `rps:2437`).

## Failure modes & recovery

- **Missing camel/oasis.** `sys.exit(1)` with an install hint (`rps:204-207`). A missing camel is actually raised earlier, uncaught, at `rps:191`, because `oasis_llm` imports camel at module top (`backend/app/utils/oasis_llm.py:18`).
- **Seal or config mismatch.** `ValueError` propagates out of `main()`. `asyncio.run` only catches `KeyboardInterrupt`/`SystemExit` (`rps:6136-6139`), so the process prints a traceback, writes the final telemetry in `finally`, and exits non-zero. [verifier: the catching is done by the `try` in `__main__` around `asyncio.run`, not by `asyncio.run` itself. A `ValueError` does exit non-zero. However, `except SystemExit: pass` makes every `sys.exit(1)` raised inside `main` (missing config `rps:5835`, disk preflight `rps:5876`, second signal `rps:6126`) exit with status 0 (`rps:6134-6139`)]
- **Canonical Reddit enforcement or attestation failure.** Raises inside `run_reddit_simulation`. `asyncio.gather(return_exceptions=True)` isolates it, so the Reddit result is `None` and Twitter continues (`rps:5930-5943`).
- **Best-effort injections.** Role clipping, world brief, calendar vocabulary, normaliser and guard are each wrapped at the call site. A failure leaves the native behaviour and logs a line (`rps:4750-4783`). [verifier: this does not hold for canonical Reddit actors. A world-brief or calendar-vocabulary injection that fails is swallowed per agent: `_inject_behavior_hint` returns False (`rps:555-556`) and the loops `continue` (`rps:734-735`, `rps:774-775`). The unwrapped attestation then finds `actual != expected` and raises `ValueError` (`rps:663-666`, `rps:5318-5324`). For canonical Reddit actors these "best-effort" injections are therefore fail-closed, and the Reddit platform is lost]
- **DB read errors.** `fetch_new_actions_from_db` prints and returns partial results (`rps:1481-1482`). Enrichment errors are printed and the row is kept unenriched (`rps:1590-1592`). Interview readback errors give `response=None` (`rps:1214-1215`).
- **IPC.**
  - A malformed command JSON is skipped on every poll and never deleted (`rps:916-917`); the client's stale sweep (≥300 s) eventually removes it (`backend/app/services/simulation_ipc.py:231-236`). [verifier: the sweep runs only inside `SimulationIPCClient.send_command`, i.e. when a client sends a *new* command (`backend/app/services/simulation_ipc.py:234-236`). The unused `SimulationIPCServer._sweep_stale` (`:572-588`) is not involved. With no further commands the file is never removed]
  - Client timeout: the client writes `.cancel`, and the server skips execution or skips the response write.
  - A single-platform interview exception returns a `failed` response.
  - A batch platform exception drops that platform's entries.
  - Idle for more than 60 minutes, or a signal, closes the envs (`rps:6060-6072`).
- **LLM failures.** OASIS swallows per-agent model exceptions inside `astep`. The counter wrapper is the only signal (`rps:2023-2028`). An error rate above 0.5 marks the platform `degraded`, and the runner downgrades health to `llm_degraded`.
- **Seed follows.** A throttle failure falls back to the uncapped lists (`rps:2501-2502`). A per-pass `env.step` failure is logged and the next pass continues (`rps:2525-2526`).

## Surprises

1. **Suspected bug: dynamics state lines never reach the model.** `_inject_agent_dynamics` writes the state with `OpenAIBackendRole.SYSTEM` (`rps:1923`). The same file says that camel 0.2.78's `ScoreBasedContextCreator` keeps only `records[0]` as the system message and drops every later SYSTEM record. That comment is why the world clock (`rps:1945-1947`, `rps:2016-2018`) and the reply-step memory (`rps:4659`) use USER instead. The library confirms it: `backend/.venv/.../camel/memories/context_creators/score_based.py:115-120` skips SYSTEM records, `:372-375` keeps only the first, and OASIS `SocialAgent` uses camel's default memory (`backend/.venv/.../oasis/social_agent/agent.py:106-111`). `SIM_AGENT_DYNAMICS` defaults to **true** (`backend/app/config.py:1399`), so the tracker runs every round with no prompt effect. `dynamics_summary().active` measures only *received signals* (`backend/app/services/agent_dynamics.py:180-188`), so the report caveat cannot detect this.
2. **Doc-vs-code drift on the dynamics default.** The comments call `SIM_AGENT_DYNAMICS` "默认关" (default off) at `rps:4965`, `rps:5078` and `rps:5162`, and "gated" at `rps:1880`. Config defaults it **on** (`backend/app/config.py:1396-1399`, "NEXTSTEPS P0-4：默认开").
3. **Suspected bug: CREATE_COMMENT rows never get parent-post context.** OASIS 0.2.5 records comment traces as `{"content","comment_id"}` only (`backend/.venv/.../oasis/social_platform/platform.py:1104`). `_enrich_action_context` keys the CREATE_COMMENT branch on `post_id` (`rps:1582-1588`), so `post_content` and `post_author_name` are never added. `agent_dynamics.extract_round_signals` resolves targets through `post_author_name` and similar keys (`backend/app/services/agent_dynamics.py:34-36`), so comments produce **no received signal** for the post's author.
4. **Suspected bug: MUTE enrichment is dead code.** OASIS records `{"mutee_id": …}` (`backend/.venv/.../oasis/social_platform/platform.py:996`). `fetch_new_actions_from_db` drops every key not in its 9-key whitelist (`rps:1447-1465`), and the MUTE branch looks for `user_id`/`target_id` (`rps:1566`). `target_user_name` is therefore never set for MUTE. The unit test feeds it synthetically (`backend/tests/test_audit_fixes_runloop.py:42-49`), which hides the gap. Similarly, the REPOST `reposted_id` is dropped; enrichment goes through `new_post_id` instead.
5. **Suspected bug: the self-like guard can be bypassed through the alias path.** The guard wraps *outside* the normaliser (normaliser at `rps:4775`/`rps:5328`, guard at `rps:4780`/`rps:5333`). It reads `kwargs["comment_id"]` before the normaliser renames a hallucinated `post_id` (`rps:2445`, `rps:2319`). A call `like_comment(post_id=<own comment id>)` therefore gets `target=None`, so `_target_author_agent_id` returns `None`, the guard is not triggered, and the inner normaliser renames the argument and executes a self-like. The guard also never covers `ManualAction` likes, because OASIS `perform_action_by_data` builds fresh tools from `env.action` (`backend/.venv/.../oasis/social_agent/agent.py:278-285`).
6. **Suspected bug: falsy-`or` defaults distort activation.** `float(cfg.get("activity_level", 0.5) or 0.5)` turns an explicit `activity_level: 0` into 0.5 (`rps:1849`), and `influence_weight: 0` into 1.0 (`rps:1833`, `rps:1850`). An agent configured to be silent still activates with p≈0.5×….
7. **Docstring drift in the sampler.**
   - The docstring says recency covers agents "上一轮活跃/被提及" (active *or mentioned*) (`rps:1813`), but callers pass only the previous round's active ids (`rps:5056`).
   - It says the target is "封顶 3×base_max" (capped at 3×base_max) (`rps:1814`), but `× multiplier` is applied after the cap (`rps:1859`), so at peak hours (1.5×) the target can reach 4.5×base_max.
   - The hour multiplier is applied twice, once to each agent's probability and once to the target count (`rps:1851`, `rps:1859`).
8. **`.env` override ordering.**
   - `_RNG` is seeded at `rps:114`, before both `.env` loads. A `SIM_SEED` that exists only in `.env` is ignored by the RNG when the script is run by hand.
   - Conversely, importing `app.config` (through `rps:191`) re-loads `.env` with `override=True` (`backend/app/config.py:20-21`). That **overwrites runner-injected child env vars** such as `SIM_RESUME` and `SIM_SEED` (`backend/app/services/simulation_runner.py:934-939`) whenever `.env` also defines them. Every later `os.environ` read in the script sees the `.env` value. (`.env` itself was not inspected; this is a mechanism, not an observed failure.)
9. **Two different empty-string semantics.** `_cfg_flag` treats an empty env var as "unset, use Config" (`rps:799-801`). Config computes booleans as `os.environ.get(X,'true').lower()=='true'`, so an *empty* `SIM_WORLD_BRIEF=` in the environment yields Config `False` (`backend/app/config.py:1409`), and the flag becomes off rather than the documented default on.
10. **Duplicated IPC server.** `ParallelIPCHandler` reimplements the server side and has no `.processing` claim (`rps:881-919`). The library's `SimulationIPCServer` with TOCTOU-safe claims (`backend/app/services/simulation_ipc.py:547`) is unused by any script. `run_twitter_simulation.py` and `run_reddit_simulation.py` each carry a third and fourth copy (`backend/scripts/run_twitter_simulation.py:153`, `backend/scripts/run_reddit_simulation.py:153`). `DRF_ARCHITECTURE.md:946-947` describes the `.processing` server as if it were the one in use.
11. **Suspected IPC hazards.**
    - (a) A command whose JSON lacks `command_id`, or whose id differs from its filename, makes `send_response` treat it as abandoned (`rps:932`). The command file is left in place, so it is re-polled and **re-executed** every ~0.5 s until the client's stale sweep removes it. [verifier: the sweep happens only when a client sends another command (`backend/app/services/simulation_ipc.py:234-236`). Each re-execution also refreshes `last_command_at` (`rps:1231`, `rps:1247`), so the `SIM_IDLE_CLOSE_MIN` auto-close (`rps:6060-6066`) never fires while such a file exists]
    - (b) `handle_batch_interview` reads back results for agents whose `get_agent` failed (`rps:1130-1134`), and `_get_interview_result` returns the *latest prior* interview for that user (`rps:1194-1200`). A stale answer, or `response=None`, is therefore reported under `completed`.
    - (c) A missing `agent_id` silently interviews agent 0 (`rps:1242`).
12. **Unused parameters and imports.**
    - `inject_initial_follows` ignores `agent_names` and `action_logger` (`rps:2460`).
    - `get_active_agents_for_round` ignores `round_num` (`rps:1806`).
    - `warnings` (`rps:87`), module-level `multiprocessing` (`rps:78`), `ModelFactory` and `ModelPlatformType` (`rps:194-195`) are unused.
    - `shutil`, `inspect` and `functools` are re-imported locally (`rps:186`, `rps:2345-2346`, `rps:2423-2424`). [verifier: only `shutil` and `inspect` are true re-imports (module-level at `rps:81` and `rps:75`). `functools` has no module-level import, so the local imports at `rps:2345` and `rps:2423` are its only imports]
13. **The audience role can still post.** The `audience` policy omits CREATE_POST "几乎不发起原创帖" (almost never starts original posts) (`rps:404-414`), but `_ROLE_ACTION_FLOOR` re-adds CREATE_POST for every role (`rps:432-436`, `rps:477`).
14. **Role hints are wiped for canonical Reddit actors.** This is intentional (`rps:5291-5293`). With `SIM_ROLE_ACTION_PROFILES=true`, the hint appended at `rps:527` is replaced by the canonical message at `rps:621`; only the tool clipping survives. The behavioural hints are also Chinese even for English runs (`rps:441-446`), and so are dynamics state lines (`backend/app/services/agent_dynamics.py:200-210`).
15. **`simulation.log` has several writers.** The runner opens `simulation.log` with `'w'` and points the child's stdout/stderr at it (`backend/app/services/simulation_runner.py:924-947`). The child's `SimulationLogManager` opens the same file again with `FileHandler(mode='w')`, which truncates it, and adds a console handler on stderr, i.e. the same file through the runner's descriptor (`backend/scripts/action_logger.py:165-180`). The two non-append descriptors keep independent offsets, so lines can overwrite each other, and every `log_info` line is emitted up to three times (logger file, logger console, `print`). Suspected log garbling; it is outside the slice, but it affects every slice log line.
16. **Doc drift in the architecture docs.**
    - `DRF_ARCHITECTURE.md:902-913` and `:988-996` cite `:190-197` for the imports (`DRF_ARCHITECTURE.md:902`) (actual `rps:190-207`), `:209`/`:222` for the action lists (actual `rps:214`/`rps:227`), `:3190`/`:3597` for the round loops (actual `rps:5008`/`rps:5559`), `:2423` for emergent metrics (actual `rps:3140`) and `:3919-3952` for the decision channel (actual `rps:5983-6026`).
    - It also says "Action tools are role-clipped per agent" (`DRF_ARCHITECTURE.md:907`), but clipping is **off by default** (`rps:793`).
    - It ties `throttle_seed_follows` to initial *posts* (`DRF_ARCHITECTURE.md:910-911`), but it throttles seed *follows* (`rps:2489-2502`).
    - `ARCHITECTURE_MAP.md:286` and `:646` say the CLI semaphore is 3; the default is 8 (`backend/app/utils/oasis_llm.py:29`).
    - The module docstring lists `run_state.json` as written here (`rps:25`), but the runner writes it.

## Verification

Adversarial verification on 2026-10-11 against branch `main`, read from disk (`backend/scripts/run_parallel_simulation.py`, 6154 lines). Third-party behaviour was checked against the installed `camel-oasis==0.2.5` and `camel-ai==0.2.78` in `backend/.venv/lib/python3.12/site-packages/`. Nothing was executed and no network or LLM calls were made.

**Verdict counts.**

- Load-bearing claims (15): 15 confirmed.
- Surprises (14): 14 confirmed.
- Spot-checked map statements: 23 checked; 14 confirmed, 9 imprecise. Each imprecise statement is annotated inline with `[verifier: …]`.
- Refuted: 0.

**Load-bearing claims and surprises, with notes on confirmed items.**

- Seal chain. `load_config` (`rps:1275-1278`), `validate_direct_child_config_seal` (`rps:1302-1335`) and the `main` hand-off (`rps:5841-5850`) behave as stated.
  - The delegate always validates `<sim_dir>/simulation_config.json`, never the `--config` path (`backend/app/services/simulation_manager.py:167-174`).
  - It returns `{}` when the manifest is absent and nothing is required. `load_config` then runs with no sha check (`backend/app/services/simulation_manager.py:146-150`).
- Reddit attestation (`rps:649-697`). It is unwrapped at the call sites (`rps:5294-5296`, `rps:5318-5324`).
- Surprise 1 (dynamics SYSTEM record dropped). Confirmed in the library.
  - `ScoreBasedContextCreator` skips every SYSTEM record and keeps only `records[0]` (`backend/.venv/lib/python3.12/site-packages/camel/memories/context_creators/score_based.py:115-120`, `:372-376`).
  - `SocialAgent` gets camel's default `ChatHistoryMemory` with that creator (`backend/.venv/lib/python3.12/site-packages/oasis/social_agent/agent.py:106-111`; `backend/.venv/lib/python3.12/site-packages/camel/agents/chat_agent.py:478-484`).
- Surprises 3 and 4 (CREATE_COMMENT and MUTE enrichment). OASIS records `{"content","comment_id"}` (`backend/.venv/lib/python3.12/site-packages/oasis/social_platform/platform.py:1104`) and `{"mutee_id"}` (`platform.py:996`). Neither carries a key the enrichment branch can use.
- Surprise 5 (self-like guard bypass). camel calls `self.func` at call time (`backend/.venv/lib/python3.12/site-packages/camel/toolkits/function_tool.py:491-498`), so the outer guard sees `post_id` before the inner normaliser renames it. `perform_action_by_data` resolves fresh tools from `env.action` (`oasis/social_agent/agent.py:278-285`).
- Surprise 8 (`.env` override). The mechanism is confirmed: `backend/app/config.py:20-24` loads `.env` with `override=True`, and importing `app.utils.oasis_llm` pulls in `app/__init__.py` and `app.config` (`backend/app/__init__.py:18`).
  - In this child, `SIM_SEED` is read only at `rps:104`, before the override, so the override cannot change `_RNG`.
  - `SIM_RESUME` is read later through `_flag_true` (`rps:3749`), so the override can change it.
- Surprise 10 (stale batch interviews). The "missing `agent_id` → agent 0" default applies only to the single-INTERVIEW path (`rps:1242`). In a batch, a missing id calls `get_agent(None)`, which only prints a warning (`rps:1118-1125`); the readback is then stored as `<platform>_None`.
- Surprise 13 (CLI semaphore). With both platforms running, each platform gets `8 // 2 = 4` (`backend/app/utils/oasis_llm.py:603-616`).

**Imprecise statements (corrections inline above).**

1. Walkthrough §3. The `action_logger` anchors are reversed: `PlatformActionLogger` is at `:22` and `SimulationLogManager` at `:134`. `SimulationLogManager` writes `simulation.log`, not JSONL (`backend/scripts/action_logger.py:22`, `:134-180`).
2. Walkthrough §5, `publicfigure`. Compared with the professor set it also drops SEARCH_POSTS (`rps:382-390`).
3. Walkthrough §19, `add_edge`. The OASIS 0.2.5 recommender and refresh never read the in-memory `AgentGraph`; they use the DB tables, and the Twitter in-network feed uses the DB `follow` table (`oasis/social_platform/platform.py:281-293`, `:329-376`). The seed-follow cap therefore truncates the follow graph that feeds see.
4. Control flow item 2. The second signal's `sys.exit(1)` is swallowed by `except SystemExit: pass`, so the process exits with status 0 (`rps:6126`, `rps:6138-6139`).
5. Failure modes, "Seal or config mismatch". The catching is done by the `try` around `asyncio.run`, not by `asyncio.run`. Every `sys.exit(1)` inside `main` exits with status 0 (`rps:5835`, `rps:5876`, `rps:6134-6139`). The runner compensates (`backend/app/services/simulation_runner.py:1089-1099`).
6. Failure modes, "Best-effort injections". For canonical Reddit actors a failed world-brief or calendar injection is silent (`rps:555-556`, `rps:734-735`, `rps:774-775`). The attestation mismatch that follows then fails the Reddit platform closed (`rps:663-666`).
7. Failure modes, IPC stale sweep. The sweep runs only when a client sends a new command (`backend/app/services/simulation_ipc.py:234-236`).
8. Surprise 11(a). Same sweep caveat. In addition, each re-execution refreshes `last_command_at` (`rps:1231`, `rps:1247`), which defeats the idle auto-close (`rps:6060-6066`).
9. Surprise 12. `functools` is not re-imported; it has no module-level import. The true re-imports are `shutil` (`rps:81`) and `inspect` (`rps:75`).

**Spot checks confirmed.**

- `ROLE_ACTION_POLICY` has 17 keys (`rps:269-415`).
- `ACTION_TYPE_MAP` has 15 entries, including `interview` (`rps:1352-1368`).
- Atomic temp files are named `.tmp-*` with no `.json` suffix, so `poll_command` never picks them up (`backend/app/utils/atomic.py:37`).
- `update_status` writes `alive` (`rps:6044`) and `stopped` (`rps:6081`).
- `_resolve_provider` checks `LLM_PROVIDER`, then `config.llm_provider`, then `Config.LLM_PROVIDER`, then `claude-cli` (`backend/app/utils/oasis_llm.py:481-487`).
- `log_round_start` accepts only `period_label`, and `log_round_end` only `period_end` (`backend/scripts/action_logger.py:68-86`).
- The OASIS Twitter template has no demographics, while the Reddit template contains the MBTI phrase (`oasis/social_platform/config/user.py:50-75`, `:94-98`).
- camel's `remove_tools(list)` exists (`camel/agents/chat_agent.py:799-802`).
- Round-loop call order: dynamics injection (`rps:5079`), world clock (`rps:5085`), fetch (`rps:5131`), reply step (`rps:5150-5155`), dynamics observation (`rps:5163`), engagement likes (`rps:5167-5172`), `_write_llm_health` (`rps:5205`).
- The seed drain skips CREATE_POST and logs the remaining rows as round 0 with `is_seed_action` (`rps:4917-4931`).
- The root-logger filter catches camel's `logging.warning` (`camel/types/unified_model_type.py:66-69`).
- Telemetry is written at `rps:5952` and in the `finally` block (`rps:6143-6147`).
- The wait loop polls every 0.5 s, with an idle close after `SIM_IDLE_CLOSE_MIN` (`rps:6049-6072`).
- `ParallelIPCHandler` has copies at `backend/scripts/run_twitter_simulation.py:153` and `backend/scripts/run_reddit_simulation.py:153`, while `SimulationIPCServer` is only exported (`backend/app/services/__init__.py:33`).

**Omissions (significant behaviour the map does not cover).**

1. **`SIM_SEED` does not make dual-platform runs reproducible.**
   - One process-global `_RNG` (`rps:114`) feeds both platforms' activation draws (`rps:1747`, `rps:1854`) and the reply and engagement phases (`rps:5154`, `rps:5170`, `rps:5705`, `rps:5721`).
   - The two loops run concurrently (`rps:5930-5936`), so which platform draws next depends on LLM latency.
   - OASIS refresh also samples with the unseeded global `random` (`oasis/social_platform/platform.py:277`).
2. **Telemetry `calls` counts successes only.** `_SIM_LLM_USAGE["calls"]` increments only in `_record_sim_llm_usage`, which runs on success (`rps:2073`, `rps:2248`, `rps:2262`). A failed call increments only `errors` (`rps:2088-2094`). The per-platform counter behind `llm_health.json` counts attempts instead (`rps:2240`, `rps:2255`). The `calls` fields in `sim_llm_telemetry.json` and `llm_health.json` therefore differ in meaning.
3. **A non-dict command JSON stops the IPC server.**
   - `poll_command` returns any parseable JSON (`rps:914-915`).
   - A list or scalar makes `command.get` raise `AttributeError` (`rps:1233`).
   - The wait loop's `except Exception` (`rps:6077-6078`) catches it, leaves the loop and closes both environments.
4. **A failed interview readback still counts as success.** `_get_interview_result` never sets an `error` key; a missing DB or failed query leaves `response=None` (`rps:1176-1217`). Single-platform and both-platform interviews count only results without `error` as failures (`rps:1024`, `rps:1062-1063`), so such a result is still reported as `completed`.
5. **Hidden clock advances on Twitter.** Every `env.step` advances the Twitter sandbox clock (`oasis/environment/env.py:197-198`). That includes each seed-follow pass (`rps:2523`) and each interview step (`rps:995`, `rps:1128`). Post `created_at` time steps on Twitter therefore drift by the number of seed-follow passes before round 1.
6. **A config row without `agent_id` is treated as agent 0.** `get_active_agents_for_round` uses `cfg.get("agent_id", 0)` (`rps:1841`), so agent 0 can be selected twice in the same round.
