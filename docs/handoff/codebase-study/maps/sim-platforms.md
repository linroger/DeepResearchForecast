# sim-platforms — Single-platform simulation scripts and action logger

Slice files (every line read):

| File | Lines | Role |
|---|---|---|
| `backend/scripts/run_twitter_simulation.py` | 1117 | Standalone OASIS **Twitter-only** subprocess: run the round loop, write `twitter/actions.jsonl`, then optionally wait for file-IPC interview commands |
| `backend/scripts/run_reddit_simulation.py` | 1108 | Standalone OASIS **Reddit-only** subprocess. It is a near-verbatim copy of the Twitter script (see the diff table below) |
| `backend/scripts/action_logger.py` | 323 | JSONL action-log writer (`PlatformActionLogger`), main-log manager (`SimulationLogManager`) and a dead legacy single-file logger (`ActionLogger`/`get_logger`) |

Branch studied: `main` checkout on disk. Anchors are `path:line` relative to the repo root. I read outside the slice only to resolve callers, OASIS behaviour (installed `camel-oasis 0.2.5` under `backend/.venv/lib/python3.12/site-packages/oasis/`) and the `run_parallel_simulation.py` counterpart.

---

## Purpose & position in the pipeline

- **Stage.** These files belong to pipeline stage 5 (RUN). `SimulationRunner.start_simulation` launches one of three scripts as a detached subprocess. `run_twitter_simulation.py` is chosen when `platform == "twitter"`, `run_reddit_simulation.py` when `platform == "reddit"`, and `run_parallel_simulation.py` otherwise (`backend/app/services/simulation_runner.py:875-886`). The child runs with `cwd=sim_dir`, with stdout+stderr going to `<sim_dir>/simulation.log` (`backend/app/services/simulation_runner.py:924-948`). A daemon monitor thread tails `<sim_dir>/{twitter,reddit}/actions.jsonl` every 2 s (`backend/app/services/simulation_runner.py:1012-1046`).
- **Who uses the single-platform scripts.** The automated pipeline never selects them. Both orchestrator start sites hard-code `{"platform": "parallel"}` (`backend/app/services/pipeline_orchestrator.py:8800`, `backend/app/services/pipeline_orchestrator.py:12975`). The single-platform scripts are reachable only in these ways: [verifier: incomplete. There is a fourth path. The DRF-2 simulation MCP tool `sim_start` takes `platform: "parallel" | "twitter" | "reddit"` and passes it to `SimulationJobService.start` → `SimulationRunner.start_simulation(platform=...)` (`drf2/engines/simulation/server.py:61-96`, `drf2/engines/simulation/jobs.py:158-185`). That server is enabled in `drf2/config/extensions_config.json:20-27`, so an agent that calls `sim_start` can launch these scripts.]
  1. `POST /api/simulation/start` with body `platform: "twitter"|"reddit"` (`backend/app/api/simulation.py:1486-1488,1538,1558-1562,1640-1646`). The Vue wrapper `startSimulation` exists (`frontend/src/api/simulation.js:86-87`), but a grep of `frontend/src` finds no call site for it.
  2. Manual CLI use. `GET /api/simulation/<id>` attaches `run_instructions` once the simulation is READY (`backend/app/api/simulation.py:806-808`). Those instructions print `python …/run_twitter_simulation.py --config …` and `python …/run_reddit_simulation.py --config …` commands (`backend/app/services/simulation_manager.py:1520-1543`).
  3. Download. `GET /api/simulation/script/<name>/download` allow-lists all four script files (`backend/app/api/simulation.py:1359-1400`).

  The cleanup note records that the scripts were kept on purpose because the runner's single-platform branches still reference them (`drf2/CLEANUP_LOCAL.md:23-27`).
- **The action logger is on the main path.** `run_parallel_simulation.py` imports `SimulationLogManager` and `PlatformActionLogger` (`backend/scripts/run_parallel_simulation.py:190`). It builds one logger per platform (`backend/scripts/run_parallel_simulation.py:5858-5860`) and threads them into its Twitter and Reddit loops. As a result, `PlatformActionLogger` defines the on-disk `actions.jsonl` contract for every simulation run, including runs the orchestrator starts. The single-platform scripts import only `PlatformActionLogger` (`backend/scripts/run_twitter_simulation.py:138`, `backend/scripts/run_reddit_simulation.py:138`).
- **What the single-platform scripts are.** They are the original MiroFish-style per-platform runners, with a later "EXECPLAN F-9-0" retrofit that makes them write the `actions.jsonl` contract (`backend/scripts/run_twitter_simulation.py:135-138,392-689,886-998`). Without the retrofit the runner would never see `simulation_end` and the run would stay RUNNING (`backend/scripts/run_twitter_simulation.py:886-887`). None of the later run-loop features of `run_parallel_simulation.py` were ported. The table under "How the single-platform scripts differ from run_parallel_simulation.py" lists what is missing.

---

## Walkthrough (source order)

### `backend/scripts/action_logger.py`

**Module docstring (`backend/scripts/action_logger.py:1-13`).** Describes this layout:
- `sim_xxx/twitter/actions.jsonl`
- `sim_xxx/reddit/actions.jsonl`
- `simulation.log`
- `run_state.json`

`run_state.json` is written by the runner, not by this module.

**`PlatformActionLogger` (`backend/scripts/action_logger.py:22-131`).** Single-platform JSONL appender.
- `__init__(platform, base_dir)` (`:25-37`) sets the following, then calls `_ensure_dir()` (`:39-41`, `os.makedirs(..., exist_ok=True)`):
  - `log_dir = <base_dir>/<platform>`
  - `log_path = <log_dir>/actions.jsonl`

  It does not create the file. The file appears on the first write.
- Every method builds a dict, then opens `log_path` in **append** mode (`'a'`, utf-8), writes `json.dumps(entry, ensure_ascii=False) + '\n'` and closes the file. There is no buffering, lock or fsync (`:65-66, :81-82, :102-103, :117-118, :130-131`). Timestamps are local naive `datetime.now().isoformat()` (`:56, :74, :93, :110, :123`).
- `log_action(round_num, agent_id, agent_name, action_type, action_args=None, result=None, success=True)` (`:43-66`) writes `{round, timestamp, agent_id, agent_name, action_type, action_args (or {}), result, success}` (`:54-63`). There is no `platform` key and no `event_type` key. In this repo every caller omits `result` and `success`, so the defaults always produce `result: null, success: true` in practice. Grepped callers: `backend/scripts/run_twitter_simulation.py:917,978`; `backend/scripts/run_reddit_simulation.py:911,969`; `backend/scripts/run_parallel_simulation.py:2555,4053,4652,4885,4923,5138,5436,5474,5689`.
- `log_round_start(round_num, simulated_hour, period_label=None)` (`:68-82`) writes `{round, timestamp, event_type:"round_start", simulated_hour}` and adds `period_label` only when it is not None (`:78-79`). The docstring says hours mode stays byte-identical.
- `log_round_end(round_num, actions_count, simulated_hours=None, period_end=None)` (`:84-103`) writes `{round, timestamp, event_type:"round_end", actions_count}`, plus optional `simulated_hours` (`:97-98`) and `period_end` (`:99-100`). The docstring (`:87-90`) states that the runner's reconciliation of `state.simulated_hours` uses `simulated_hours` as its only source, so if the key is absent the value stays 0.
- `log_simulation_start(config, total_rounds)` (`:105-118`) writes `{timestamp, event_type:"simulation_start", platform, total_rounds, agents_count=len(config.agent_configs)}`. The caller must pass `total_rounds`. The docstring explains this replaced the stale `total_simulation_hours*2` formula (`:106-108`).
- `log_simulation_end(total_rounds, total_actions)` (`:120-131`) writes `{timestamp, event_type:"simulation_end", platform, total_rounds, total_actions}`. The runner treats this record as proof that the platform completed (see Control flow).

**`SimulationLogManager` (`backend/scripts/action_logger.py:134-211`).** Only `run_parallel_simulation.py` uses it (`backend/scripts/run_parallel_simulation.py:5858`).
- `__init__(simulation_dir)` (`:140-153`) stores the directory, sets the two platform loggers to None and calls `_setup_main_logger()`.
- `_setup_main_logger` (`:155-182`):
  - Creates the stdlib logger `simulation.<basename(sim_dir)>` at INFO level (`:160-161`) and clears any existing handlers (`:162`).
  - Adds a `FileHandler(<sim_dir>/simulation.log, mode='w')` with format `'%(asctime)s - %(levelname)s - %(message)s'` (`:157, :165-171`).
  - Adds a console `StreamHandler()`, which writes to stderr by default, with format `'[%(asctime)s] %(message)s'` (`:174-180`).
  - Sets `propagate=False` (`:182`).
- `get_twitter_logger` / `get_reddit_logger` (`:184-194`) lazily create and cache one `PlatformActionLogger` per platform.
- `log(message, level="info")` (`:196-199`) dispatches through `getattr(logger, level.lower(), logger.info)`, so an unknown level falls back to info. The wrappers `info`, `warning`, `error` and `debug` are at `:201-211`. Because the logger level is INFO, `debug()` messages are dropped.

**Legacy `ActionLogger` (`backend/scripts/action_logger.py:214-306`).** Labelled "compatible with the old interface; use SimulationLogManager instead" (`:216-220`).
- Writes to one arbitrary `log_path`, creating its parent directory (`:222-229`). Every record carries a `platform` field (`:245, :261, :274, :287, :299`).
- `log_simulation_start(platform, config)` still computes `total_rounds = time_config.total_simulation_hours (default 72) * 2` (`:289`), which is the stale formula `PlatformActionLogger` fixed.
- `log_round_end` supports `simulated_hours` but not `period_end` (`:269-282`).

**`_global_logger` / `get_logger(log_path=None)` (`backend/scripts/action_logger.py:309-323`).** Process-wide singleton. Each call that passes a `log_path` replaces the singleton. Otherwise the first call defaults to the relative path `"actions.jsonl"` in the current directory (`:320-321`). A repo-wide grep finds no importer of `ActionLogger` or `get_logger` from this module. The only `from action_logger import` lines are `backend/scripts/run_twitter_simulation.py:138`, `backend/scripts/run_reddit_simulation.py:138`, `backend/scripts/run_parallel_simulation.py:190`, `backend/tests/test_calendar_round_loop.py:34` and `backend/tests/test_sim_reaction_phase.py:34`. The legacy class is therefore dead code (see Surprises). The runner still reads a legacy single root `<sim_dir>/actions.jsonl` as a fallback when both per-platform files yield no actions (`backend/app/services/simulation_runner.py:1847-1855`). That is the file this legacy class would write.

### `backend/scripts/run_twitter_simulation.py`

Unless a row says "Reddit" or "both files differ", the Reddit file has the same code at the same line numbers up to line 691 and at shifted lines afterwards. The full diff is in the next subsection.

**Module docstring (`:1-14`).** Says that after the run the environment stays open and waits for IPC `interview` / `batch_interview` / `close_env` commands. `--no-wait` closes it immediately.

**Process globals (`:28-30`).** `_shutdown_event` is created in `main()`. `_cleanup_done` is a flag for the signal handler.

**Path and environment bootstrap (`:33-47`).**
- Inserts `backend/scripts` and `backend/` into `sys.path` (`:36-37`), so `action_logger` and `app.*` can be imported.
- `load_dotenv(<repo>/.env)`, falling back to `backend/.env` (`:40-47`). This happens silently. The parallel script prints the path it loaded (`backend/scripts/run_parallel_simulation.py:126-134`).

**`UnicodeFormatter` (`:53-67`).** A logging formatter that rewrites literal `\uXXXX` escapes in the formatted record into real characters (regex `:56`). Bad code points are left unchanged (`:61-65`).

**`MaxTokensWarningFilter` (`:70-77`) plus a root-logger filter installed at import time (`:81`).** It drops records whose message contains both "max_tokens" and "Invalid or missing". See Surprises: a filter on the root logger does not see records that propagate up from child loggers.

**`setup_oasis_logging(log_dir)` (`:84-115`).**
- Creates `<sim_dir>/log/` and deletes every `*.log` file in it, ignoring `OSError` (`:86-95`).
- Gives each of 5 OASIS loggers its own DEBUG-level `FileHandler(mode='w')` with `UnicodeFormatter` and `propagate=False` (`:97-115`). The loggers are `social.agent`, `social.twitter`, `social.rec`, `oasis.env` and `table` (`:99-105`).
- The Reddit file uses the identical list, including `social.twitter` (`backend/scripts/run_reddit_simulation.py:99-105`).
- Effect: verbose per-agent OASIS logs. `run_parallel_simulation.py` does the opposite. It raises these loggers to CRITICAL and `rmtree`s `log/` (`backend/scripts/run_parallel_simulation.py:152-185`).

**LLM factory import (`:118`).** `from app.utils.oasis_llm import create_oasis_model, get_oasis_semaphore`. This imports the backend `app` package and `Config` into the subprocess.

**OASIS and camel import guard (`:120-133`).**
- Imports `ModelFactory` and `ModelPlatformType`, which are never used afterwards, plus `oasis`, `ActionType`, `LLMAction`, `ManualAction` and `generate_twitter_agent_graph`. The Reddit file imports `generate_reddit_agent_graph` instead (`backend/scripts/run_reddit_simulation.py:128`).
- On `ImportError` it prints an install hint and calls `sys.exit(1)` (`:130-133`). This runs at module level, outside the `__main__` `SystemExit` swallow, so the exit code really is 1.

**`from action_logger import PlatformActionLogger` (`:135-138`).** Carries the F-9-0 rationale comment.

**IPC constants (`:141-144`).** `ipc_commands/`, `ipc_responses/`, `env_status.json`. **`CommandType` (`:146-150`)**: `interview`, `batch_interview`, `close_env`.

**`IPCHandler` (`:153-389`).** The child-side file-mailbox server.
- `__init__(simulation_dir, env, agent_graph)` (`:156-167`) makes both IPC directories. `self._running` is set but never read (`:163`).
- `update_status(status)` (`:169-175`) overwrites `env_status.json` with `{status, timestamp}` through a plain, non-atomic `json.dump`.
- `poll_command()` (`:177-198`):
  - Lists `ipc_commands/*.json` and sorts them by mtime (`:183-189`).
  - Returns the first one that parses (`:191-196`). Unparsable files are skipped but not deleted.
  - Has no `.cancel` marker handling. Compare `ParallelIPCHandler.poll_command` (`backend/scripts/run_parallel_simulation.py:881-919`).
- `send_response(command_id, status, result=None, error=None)` (`:200-219`):
  - Writes `ipc_responses/<command_id>.json` with `{command_id, status, result, error, timestamp}` through a plain, non-atomic `json.dump` (`:210-212`).
  - Then deletes `ipc_commands/<command_id>.json` (`:215-219`).
  - It always writes, even if the client has already timed out. The parallel handler skips the write when it finds a `.cancel` marker (`backend/scripts/run_parallel_simulation.py:921-944`).
- `handle_interview(command_id, agent_id, prompt)` (`:221-253`):
  - Runs `agent_graph.get_agent(agent_id)`, then `env.step({agent: ManualAction(INTERVIEW, {"prompt": prompt})})` (`:230-240`).
  - Reads the answer back with `_get_interview_result` and responds `"completed"` (`:243-247`).
  - Any exception produces a `"failed"` response carrying `str(e)` (`:249-253`).
- `handle_batch_interview(command_id, interviews)` (`:255-305`):
  - Builds `{agent: ManualAction(INTERVIEW)}` for each item whose agent resolves. Unresolvable agents are only printed (`:267-279`).
  - If none resolve, it responds `"failed"` with the error "没有有效的Agent" (no valid agent) (`:281-283`).
  - Otherwise it runs one `env.step` (`:286`) and then `result={"interviews_count": n, "results": {agent_id: {...}}}` (`:289-297`). **The results dict is keyed by the bare integer `agent_id`, which becomes the JSON key "0", "1", and so on.**
- `_get_interview_result(agent_id)` (`:307-348`):
  - Opens `<sim_dir>/twitter_simulation.db` (Reddit: `reddit_simulation.db`, `backend/scripts/run_reddit_simulation.py:309`).
  - Runs `SELECT user_id, info, created_at FROM trace WHERE action=? AND user_id=? ORDER BY created_at DESC LIMIT 1` with `ActionType.INTERVIEW.value` (`:325-331`).
  - Returns `{agent_id, response: info.response (or the whole info dict), timestamp: created_at}`. On a JSON parse failure, `response` is the raw string (`:336-341`). If the DB is missing it returns a null response (`:317-318`).
- `process_commands()` (`:350-389`):
  - Reads one command per call and dispatches on `command_type`. The argument defaults are `agent_id=0`, `prompt=""` and `interviews=[]` (`:367-380`). An `args.platform` key is ignored.
  - `close_env` responds `"completed"` and returns False, which tells the caller to exit the wait loop (`:382-385`).
  - An unknown type responds `"failed"` (`:387-389`).
  - Return value: True means keep waiting.

**Action-log helpers, the F-9-0 port (`:392-689`).** These are functional copies of the parallel helpers (`backend/scripts/run_parallel_simulation.py:1349-1721`). Only docstrings and the key-copy loop style differ.
- `FILTERED_ACTIONS = {'refresh', 'sign_up'}` (`:394`).
- `ACTION_TYPE_MAP` (`:397-413`). It maps 15 OASIS trace action names to upper-case names. Unmapped names fall through to `.upper()` (`:485`).
- `get_agent_names_from_config(config)` (`:416-430`) returns `{agent_id: entity_name}` from `config.agent_configs`. `entity_name` defaults to `Agent_<id>`, and entries without `agent_id` are skipped.
- `fetch_new_actions_from_db(db_path, last_rowid, agent_names)` (`:433-501`):
  - Runs `SELECT rowid, user_id, action, info FROM trace WHERE rowid > ? ORDER BY rowid` (`:455-460`). The cursor advances to the last rowid seen, including filtered rows (`:463`).
  - Filters `refresh` and `sign_up` (`:466-467`) and parses `info` JSON, using `{}` on error (`:470-473`).
  - Keeps only these keys (`:477-482`): `content`, `post_id`, `comment_id`, `quoted_id`, `new_post_id`, `follow_id`, `query`, `like_id`, `dislike_id`.
  - Maps the type (`:485`), enriches the record (`:488`), and appends `{agent_id: user_id, agent_name, action_type, action_args}` (`:490-495`).
  - Any exception is printed and returns whatever was collected so far (`:498-501`). If the DB is missing it returns `([], last_rowid)` (`:448-449`).
  - Because OASIS 0.2.5 inserts `user_id = agent_id` at sign-up (`backend/.venv/lib/python3.12/site-packages/oasis/social_platform/platform.py:187-195`), `agent_names.get(user_id)` resolves correctly.
- `_enrich_action_context(cursor, action_type, action_args, agent_names)` (`:504-597`). This mutates `action_args` in place:
  - LIKE_POST / DISLIKE_POST add `post_content` and `post_author_name` (`:513-519`).
  - REPOST looks up `post.original_post_id` from `new_post_id`, then adds `original_content` and `original_author_name` (`:522-534`).
  - QUOTE_POST adds the original post info from `quoted_id` plus `quote_content` from the new post (`:537-553`).
  - FOLLOW resolves `follow.followee_id` and adds `target_user_name` (`:556-567`).
  - MUTE reads `user_id` or `target_id` (`:570-575`).
  - LIKE_COMMENT / DISLIKE_COMMENT add `comment_content` and `comment_author_name` (`:578-584`).
  - CREATE_COMMENT adds the parent post info from `post_id` (`:587-593`).
  - Any exception is printed and swallowed (`:595-597`).
- `_get_post_info` (`:600-631`) and `_get_comment_info` (`:658-689`) join `post`/`comment` with `user`. The author name is the config name when `user.agent_id` is in `agent_names`, otherwise `user.name` or `user.user_name`. Exceptions return None.
- `_get_user_name` (`:634-655`) follows the same precedence, starting from a `user_id`.

**`TwitterSimulationRunner` (`:692-1040`). Reddit: `RedditSimulationRunner` (`backend/scripts/run_reddit_simulation.py:692-1030`).**
- `AVAILABLE_ACTIONS`:
  - Twitter has 6 (`:696-703`): `CREATE_POST`, `LIKE_POST`, `REPOST`, `FOLLOW`, `DO_NOTHING`, `QUOTE_POST`.
  - Reddit has 13 (`backend/scripts/run_reddit_simulation.py:696-710`): `LIKE_POST`, `DISLIKE_POST`, `CREATE_POST`, `CREATE_COMMENT`, `LIKE_COMMENT`, `DISLIKE_COMMENT`, `SEARCH_POSTS`, `SEARCH_USER`, `TREND`, `REFRESH`, `DO_NOTHING`, `FOLLOW`, `MUTE`.
  - The Reddit list equals the parallel `REDDIT_ACTIONS` (`backend/scripts/run_parallel_simulation.py:227-241`). The parallel `TWITTER_ACTIONS` adds `CREATE_COMMENT`, `SEARCH_POSTS` and `TREND` (`backend/scripts/run_parallel_simulation.py:214-224`), which the single Twitter script does not have.
- `__init__(config_path, wait_for_commands=True)` (`:705-719`) loads the config JSON immediately (`:721-724`) and sets `simulation_dir = os.path.dirname(config_path)` (`:715`), with no `"."` fallback.
- `_get_profile_path` returns `<sim_dir>/twitter_profiles.csv` (`:726-728`). Reddit returns `<sim_dir>/reddit_profiles.json` (`backend/scripts/run_reddit_simulation.py:733-735`). `_get_db_path` returns `<sim_dir>/twitter_simulation.db` (`:730-732`); Reddit returns `reddit_simulation.db` (`backend/scripts/run_reddit_simulation.py:737-739`).
- `_create_model()` is `create_oasis_model(config, use_boost=False)` (`:734-740`). Reddit uses `use_boost=True` (`backend/scripts/run_reddit_simulation.py:741-748`). Boost only matters on the openai-compat path when `LLM_BOOST_API_KEY` is set (`backend/app/utils/oasis_llm.py:495-506`).
- `_get_active_agents_for_round(env, current_hour, round_num)` (`:742-809`). `round_num` is unused.
  - Reads `agents_per_hour_min` (default 5) and `agents_per_hour_max` (default 20) (`:763-764`).
  - Reads `peak_hours` (default `[9,10,11,14,15,20,21,22]`) and `off_peak_hours` (default `[0..5]`) (`:767-768`).
  - The multiplier is `peak_activity_multiplier` (default 1.5) in peak hours, `off_peak_activity_multiplier` (default 0.3) in off-peak hours, and 1.0 otherwise (`:770-775`).
  - `target = int(uniform(min,max)*multiplier)` (`:777`).
  - The candidates are agents whose `active_hours` contains the current hour (default `range(8,23)`) and that pass `random.random() < activity_level` (default 0.5) (`:780-792`).
  - `random.sample(candidates, min(target, len))` (`:795-798`). This uses the unseeded module-level `random`.
  - Returns `[(agent_id, agent)]`, silently skipping ids that `get_agent` cannot resolve (`:801-809`).
- `run(max_rounds=None)` (`:811-1040`):
  1. Prints a banner (`:817-822`). Computes `total_rounds = (total_simulation_hours (72) * 60) // minutes_per_round (60)` (`:825-830`). The value is truncated to `max_rounds` only when `max_rounds > 0` (`:833-837`).
  2. Builds the model (`:849`). If the profile file is missing it prints an error and **returns** (`:853-856`). In that case no actions file and no env are created.
  3. Calls `generate_twitter_agent_graph(profile_path, model, AVAILABLE_ACTIONS)` (`:858-862`).
  4. Deletes any existing `<platform>_simulation.db` (`:865-868`).
  5. Calls `oasis.make(agent_graph, platform=DefaultPlatformType.TWITTER, database_path, semaphore=get_oasis_semaphore(config, use_boost=False))`, then `await env.reset()` (`:872-879`). Reddit uses `REDDIT` and `use_boost=True` (`backend/scripts/run_reddit_simulation.py:858-865`). Neither passes `platforms=`, so each script gets the whole semaphore cap. [verifier: `get_oasis_semaphore` never reads `use_boost` (`backend/app/utils/oasis_llm.py:603-616`). Reddit's `use_boost=True` on the semaphore therefore has no effect. Boost affects only the model (`backend/app/utils/oasis_llm.py:490-506`).]
  6. Builds `IPCHandler` and writes `env_status=running` (`:883-884`).
  7. Builds `PlatformActionLogger("twitter", sim_dir)` (`:888`). Gets `agent_names` from the config and backfills missing ids from the agent objects with `getattr(agent,'name',...)` (`:889-893`).
  8. Sets `last_rowid=0` and `total_actions=0` (`:894-895`). Writes `simulation_start` with the computed `total_rounds` (`:896`).
  9. **Round 0 (seed posts)** (`:899-933`):
     - Writes `round_start(0, 0)` (`:903`).
     - For each item in `event_config.initial_posts` it resolves `poster_agent_id` (default 0) (`:907-911`).
     - **Twitter:** `initial_actions[agent] = ManualAction(CREATE_POST)` (`:912-915`). This overwrites any earlier post by the same agent.
     - **Reddit:** multiple posts by the same agent are merged into a list (`backend/scripts/run_reddit_simulation.py:898-909`).
     - Each successfully resolved post is logged immediately as a round-0 `CREATE_POST` with `{"content": …}`, and `total_actions` is incremented (`:917-924`). A failure to resolve is printed and skipped (`:925-926`).
     - Runs one `env.step(initial_actions)`, not wrapped in try/except (`:928-930`).
     - Advances `last_rowid` past all trace rows written so far, so the seed posts are not logged twice (`:932`).
     - Writes `round_end(0, len(initial_posts))` (`:933`).
  10. **Main loop** for `round_num` in `range(total_rounds)` (`:939-995`):
      - Computes `simulated_hour = (round_num*minutes_per_round//60) % 24` and `simulated_day` (`:941-943`). There is no start-hour offset.
      - Writes `round_start(round_num+1, simulated_hour)` (`:946`).
      - Selects active agents (`:949-951`). If there are none, it writes `round_end(r, 0)` and continues (`:953-956`).
      - Builds `{agent: LLMAction()}` (`:959-962`) and runs `env.step` in a try block. On an exception it prints the error, writes `round_end(r, 0)` and continues (`:965-971`). There is no consecutive-failure breaker.
      - Calls `fetch_new_actions_from_db`, logs each new action under round `r`, and increments `total_actions` (`:974-985`).
      - Writes `round_end(r, len(new_actions))` (`:986`).
      - Prints progress at round 1 and every 10 rounds (`:989-995`). [verifier: the print is skipped when that round is empty or its step failed, because those paths `continue` before it (`backend/scripts/run_twitter_simulation.py:956,971`).]
  11. Writes `simulation_end(total_rounds, total_actions)` (`:998`) and prints a summary (`:1000-1004`).
  12. If `wait_for_commands` is set (`:1007-1033`):
      - Sets `env_status=alive` (`:1013`).
      - Loops `process_commands()` until it returns False or `_shutdown_event` is set. Each pass waits 0.5 s on the event (`:1016-1025`). There is **no idle timeout**.
      - `KeyboardInterrupt`, `CancelledError` and generic exceptions are printed (`:1026-1031`).
  13. Always writes `env_status=stopped` and calls `await env.close()` (`:1036-1037`). [verifier: "always" holds only on the normal path. These lines are not in a `finally`. They are skipped when `run()` raises earlier, for example from the unguarded seed `env.step` (`backend/scripts/run_twitter_simulation.py:928-929`) or from an `OSError` while writing the action log.]
- `main()` (`:1043-1083`):
  - argparse accepts `--config` (required), `--max-rounds` (int, default None; comment RUN-3) and `--no-wait` (`:1044-1065`). There is **no `--resume`, no `--config-seal` and no `--twitter-only`**.
  - Creates `_shutdown_event` (`:1068-1069`).
  - If the config is missing it prints an error and calls `sys.exit(1)` (`:1071-1073`).
  - `setup_oasis_logging(<dirname(config) or ".">/log)` (`:1076-1077`).
  - Runs the runner (`:1079-1083`).
- `setup_signal_handlers()` (`:1086-1105`). The first SIGTERM or SIGINT prints a message, sets `_cleanup_done` and sets `_shutdown_event`. A second signal calls `sys.exit(1)`.
- `__main__` (`:1108-1117`). Installs the handlers, then runs `asyncio.run(main())`. It catches `KeyboardInterrupt` (print) and **`SystemExit` (`pass`)**, and the `finally` prints "模拟进程已退出" (simulation process exited).

### Diff: `run_reddit_simulation.py` vs `run_twitter_simulation.py`

`diff` of the two files shows only these semantic differences. Everything else is identical or a comment change.

| Aspect | Twitter | Reddit |
|---|---|---|
| Agent-graph builder | `generate_twitter_agent_graph` (`backend/scripts/run_twitter_simulation.py:128,858`) | `generate_reddit_agent_graph` (`backend/scripts/run_reddit_simulation.py:128,846`) |
| Profile file | `twitter_profiles.csv` (`backend/scripts/run_twitter_simulation.py:728`) | `reddit_profiles.json` (`backend/scripts/run_reddit_simulation.py:735`) |
| DB file | `twitter_simulation.db` (`backend/scripts/run_twitter_simulation.py:309,732`) | `reddit_simulation.db` (`backend/scripts/run_reddit_simulation.py:309,739`) |
| Action allowlist | 6 actions (`backend/scripts/run_twitter_simulation.py:696-703`) | 13 actions (`backend/scripts/run_reddit_simulation.py:696-710`) |
| Model / semaphore boost | `use_boost=False` (`backend/scripts/run_twitter_simulation.py:740,876`) | `use_boost=True` (`backend/scripts/run_reddit_simulation.py:748,862`) |
| OASIS platform | `DefaultPlatformType.TWITTER` (`backend/scripts/run_twitter_simulation.py:874`) | `DefaultPlatformType.REDDIT` (`backend/scripts/run_reddit_simulation.py:860`) |
| Log dir | `twitter/actions.jsonl` (`backend/scripts/run_twitter_simulation.py:888`) | `reddit/actions.jsonl` (`backend/scripts/run_reddit_simulation.py:874`) |
| Same-agent multiple seed posts | dict overwrite: only the last post executes (`backend/scripts/run_twitter_simulation.py:912-915`) | merged into a list (`backend/scripts/run_reddit_simulation.py:898-909`) |

### How the single-platform scripts differ from `run_parallel_simulation.py`

The parallel script runs per-platform loops `run_twitter_simulation(...)` (`backend/scripts/run_parallel_simulation.py:4692`) and `run_reddit_simulation(...)` (`backend/scripts/run_parallel_simulation.py:5228`). Its `main()` gathers them with `return_exceptions=True` (`backend/scripts/run_parallel_simulation.py:5926-5943`) or runs just one with `--twitter-only` / `--reddit-only` (`backend/scripts/run_parallel_simulation.py:5794-5803,5920-5925`). Despite the shared names, these are functions inside the parallel module, not the standalone scripts. The tests that say "run_twitter_simulation" call `rps.run_twitter_simulation`, where `rps` is `run_parallel_simulation` (`backend/tests/test_calendar_round_loop.py:33,246`). The single-platform scripts lack all of the following:

| Feature (parallel anchor) | Single-platform scripts |
|---|---|
| CLI `--config-seal` validation (`backend/scripts/run_parallel_simulation.py:5787-5792,5841-5851`) | absent. The runner passes it only to the parallel script (`backend/app/services/simulation_runner.py:912-913`) |
| `--resume` + per-round `checkpoint.json` (RUN-7) (`backend/scripts/run_parallel_simulation.py:5818-5825,4792-4810,4992-4996`) | absent. The runner forces a fresh run for single-platform (`backend/app/services/simulation_runner.py:773-777`) |
| `SIM_SEED`-seeded `_RNG` (`backend/scripts/run_parallel_simulation.py:102-117`) | global unseeded `random` (`backend/scripts/run_twitter_simulation.py:777,791,795`). `SIM_SEED`, which the runner injects (`backend/app/services/simulation_runner.py:934-935`), is ignored |
| Calendar mode (`temporal_config`, `_resolve_total_rounds`, period context, `period_label`/`period_end` on round events) (`backend/scripts/run_parallel_simulation.py:2591-2623,4945-4958,5021-5029,5083-5096`) | absent. Always the hours formula. Round events never carry `period_*` or `simulated_hours` |
| `simulated_hours` on every `round_end` (`backend/scripts/run_parallel_simulation.py:4937,5067-5070,5114-5117,5185-5188`) | omitted (`backend/scripts/run_twitter_simulation.py:933,955,970,986`) |
| Start-hour offset `SIM_START_HOUR` / `time_config.start_hour` (RUN-4) (`backend/scripts/run_parallel_simulation.py:1772-1782,4855`) | hour starts at 0 (`backend/scripts/run_twitter_simulation.py:942`) |
| Influence-weighted, recency-boosted, cast-scaled activation, and morning/work multipliers (`backend/scripts/run_parallel_simulation.py:1752-1769,1802-1876`) | flat `uniform(min,max)*multiplier` with peak/off-peak only (`backend/scripts/run_twitter_simulation.py:742-809`) |
| Initial follows, scheduled events, reaction phase, engagement sampler, dynamics, world brief, role action profiles, self-like guard, tool-arg normalizer, in-band world evolution (`backend/scripts/run_parallel_simulation.py:4747-4785,4906-4910,4966,5038-5048,5150-5182`) | none |
| Per-round disk preflight + consecutive `env.step` failure breaker (XRUN-4) (`backend/scripts/run_parallel_simulation.py:5005-5007,5033-5035,5105-5127`) | none. Failed rounds are skipped forever |
| Shutdown-event check inside the round loop (`backend/scripts/run_parallel_simulation.py:5010-5013`) | absent. Only the wait loop checks it (`backend/scripts/run_twitter_simulation.py:1017`) |
| `llm_health.json`, `*_dynamics_summary.json`, `sim_llm_telemetry.json`, emergent metrics, decision channel (`backend/scripts/run_parallel_simulation.py:5205-5218,5952,5957-5970,5984-6030`) | none of these artifacts |
| IPC `.cancel` handling, atomic writes, platform-tagged results (`twitter_<id>`), `SIM_IDLE_CLOSE_MIN` idle close (default 60) (`backend/scripts/run_parallel_simulation.py:881-944,1134,1161,6046-6066`) | none of these. Results are keyed by bare id, and the process waits forever |
| OASIS logging disabled (`backend/scripts/run_parallel_simulation.py:152-185`) | OASIS logging at DEBUG to `log/*.log` (`backend/scripts/run_twitter_simulation.py:84-115`) |
| `SimulationLogManager` main log (`backend/scripts/run_parallel_simulation.py:5858-5869`) | `print()` only, captured by the runner's stdout redirect |

---

## Control flow

1. **Launch.** `POST /api/simulation/start` (`backend/app/api/simulation.py:1486-1646`) calls `SimulationRunner.start_simulation(platform="twitter"|"reddit")` (`backend/app/services/simulation_runner.py:451-476`). The runner then:
   - validates the platform name (`:473-476`);
   - runs the LOOP-011 role-manifest checks (`backend/app/services/simulation_runner.py:497-759`);
   - **forces resume off for non-parallel platforms** (`backend/app/services/simulation_runner.py:773-777`);
   - rotates stale logs to `*.prev` (`backend/app/services/simulation_runner.py:783-786,1310-1338`);
   - computes `state.total_rounds` (`:808-833`);
   - sets `twitter_enabled`/`reddit_enabled` for the chosen platform only (`:875-882`);
   - builds `[sys.executable, script, --config, path] (+ --max-rounds N)` (`:907-918`);
   - spawns the child with `Popen(cwd=sim_dir, stdout=simulation.log, stderr=STDOUT, start_new_session=True)` and an env containing `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` and optionally `SIM_SEED`/`SIM_RESUME` (`:924-953`);
   - starts the monitor thread (`:969-975`).
2. **Child process.** `__main__` (`backend/scripts/run_twitter_simulation.py:1108-1117`) → `setup_signal_handlers` (`:1086-1105`) → `main` (`:1043-1083`) → `setup_oasis_logging` (`:84-115`) → `TwitterSimulationRunner(...)` (`:705-719`) → `run()` (`:811-1040`). Inside `run()`:
   - model, agent graph, DB reset, `oasis.make`, `env.reset`;
   - `IPCHandler.update_status("running")`;
   - `simulation_start`;
   - round 0 seed posts;
   - rounds 1..N: `round_start` → activate → `env.step(LLMAction)` → `fetch_new_actions_from_db` → `log_action`×k → `round_end`;
   - `simulation_end`;
   - optional `alive` wait loop processing IPC;
   - `stopped` → `env.close()`.
3. **Parent monitoring.** `_monitor_simulation` reads both per-platform logs incrementally by byte offset while the process lives (`backend/app/services/simulation_runner.py:1029-1046`). `_read_action_log` (`backend/app/services/simulation_runner.py:1149-1295`) handles each record type:
   - `simulation_end` sets `twitter_completed`/`reddit_completed`. If all enabled platforms are complete and the status is STARTING/RUNNING, it marks **COMPLETED immediately**, without waiting for process exit (`:1186-1222`).
   - `round_end` updates per-platform `current_round` (max) and `simulated_hours` (`:1225-1255`).
   - Any record without `event_type` becomes an `AgentAction` with `platform` taken from the file being tailed (`:1259-1276`). It is optionally fed to the Zep graph updater (`:1280-1281`).
4. **Exit reconciliation.** After the process exits, the runner:
   - keeps an existing COMPLETED/FAILED/STOPPED status;
   - converts STOPPING to STOPPED;
   - treats `exit 0` with all platforms complete as COMPLETED;
   - otherwise marks FAILED. That includes `exit 0` without `simulation_end` (LOOP-001) (`backend/app/services/simulation_runner.py:1063-1104`).

   It then writes `env_status=stopped` (`:1112`).
5. **Interviews.** API, runner and MCP calls go through `SimulationIPCClient.send_command`, which writes `ipc_commands/<uuid>.json` atomically and polls `ipc_responses/<uuid>.json` (`backend/app/services/simulation_ipc.py:209-322`). The client refuses unless `env_status.status == "alive"` (`backend/app/services/simulation_ipc.py:424-439`) [verifier: `send_command` does not check this itself (`backend/app/services/simulation_ipc.py:209-342`). The callers enforce the gate through `check_env_alive()`: the runner (`backend/app/services/simulation_runner.py:2683,2772,2888`), the API (`backend/app/api/simulation.py:2383,2518`) and the MCP server (`backend/app/mcp/sim_server.py:98`).], so interviews are only possible after `simulation_end` and only without `--no-wait`.
6. **Stop.** The runner sends SIGTERM to the process group, waits 10 s, then sends SIGKILL (`backend/app/services/simulation_runner.py:1609-1662`).
   - In the round loop, the single-platform child only sets the event. The loop does not check it, so the child keeps running until SIGKILL.
   - In the wait loop, the event ends the loop within 0.5 s, and the child then writes `stopped` and closes the env.

---

## Data & artifacts

**Reads (child):**
- `<sim_dir>/simulation_config.json`. The path comes from `--config`; `json.load` (`backend/scripts/run_twitter_simulation.py:721-724`). Keys used:
  - `time_config.{total_simulation_hours, minutes_per_round, agents_per_hour_min/max, peak_hours, off_peak_hours, peak_activity_multiplier, off_peak_activity_multiplier}` (`:759-775, :825-827`);
  - `agent_configs[].{agent_id, entity_name, active_hours, activity_level}` (`:422-428, :780-784`);
  - `event_config.initial_posts[].{poster_agent_id, content}` (`:899-909`);
  - `simulation_id` (print only, `:820`);
  - `llm_provider` / `llm_model` (via `backend/app/utils/oasis_llm.py:481-487,568`).
- `<sim_dir>/twitter_profiles.csv` or `<sim_dir>/reddit_profiles.json`, consumed by the OASIS graph builders (`:858-862`).
- `<repo>/.env` or `backend/.env` through dotenv (`:40-47`).
- `ipc_commands/*.json`: `{command_id, command_type, args}` (`:177-198, :361-363`).

**Writes (child):**
- `<sim_dir>/{twitter|reddit}_simulation.db`. Deleted at start (`:865-868`) and created by OASIS. Tables read here: `trace(rowid,user_id,action,info,created_at)`, `post(post_id, content, user_id, original_post_id, quote_content)`, `comment(comment_id, content, user_id)`, `follow(follow_id, followee_id)`, `user(user_id, agent_id, name, user_name)` (`:455-460, :525-527, :548-550, :559-561, :607-612, :641-643, :665-670`).
- `<sim_dir>/{platform}/actions.jsonl`. Append-only JSONL. Sequence for a single-platform run with N rounds:
  - `{"timestamp", "event_type":"simulation_start", "platform", "total_rounds":N, "agents_count"}` (`backend/scripts/action_logger.py:109-115`)
  - `{"round":0, "timestamp", "event_type":"round_start", "simulated_hour":0}`
  - zero or more `{"round":0, "timestamp", "agent_id", "agent_name", "action_type":"CREATE_POST", "action_args":{"content"}, "result":null, "success":true}`
  - `{"round":0, …, "event_type":"round_end", "actions_count": len(initial_posts)}`
  - for r = 1..N: `round_start(r, hour)`, then the actions for round r (`action_args` holds the kept keys plus enrichment keys `post_content`, `post_author_name`, `original_content`, `original_author_name`, `quote_content`, `target_user_name`, `comment_content`, `comment_author_name`), then `round_end(r, k)`
  - `{"timestamp", "event_type":"simulation_end", "platform", "total_rounds":N, "total_actions"}`

  Action records carry no `platform` key. Readers infer the platform from the directory (`backend/app/services/simulation_runner.py:1824-1841`).
- `<sim_dir>/env_status.json`: `{status: running|alive|stopped, timestamp}` (`:169-175, :884, :1013, :1036`).
- `<sim_dir>/ipc_responses/<command_id>.json`: `{command_id, status: completed|failed, result, error, timestamp}` (`:200-212`). Result shapes:
  - interview: `{agent_id, response, timestamp}` (`:311-341`);
  - batch: `{interviews_count, results: {"<agent_id>": {...}}}` (`:294-297`);
  - close: `{message}` (`:384`).
- `<sim_dir>/log/{social.agent,social.twitter,social.rec,oasis.env,table}.log`. OASIS DEBUG logs, truncated per run (`:84-115`).
- stdout/stderr: all `print()` output lands in `<sim_dir>/simulation.log` through the runner's redirect (`backend/app/services/simulation_runner.py:924-944`).

**`SimulationLogManager` (parallel runs only):** writes `<sim_dir>/simulation.log` with `mode='w'` (`backend/scripts/action_logger.py:157,165`) and echoes to stderr (`:174-180`).

**In-memory structures:**
- `agent_names: Dict[int,str]` (`backend/scripts/run_twitter_simulation.py:889-893`);
- `last_rowid` (trace cursor, `:894`);
- `total_actions` (`:895`);
- `initial_actions: Dict[SocialAgent, ManualAction|list]` (`:906`);
- `actions: Dict[SocialAgent, LLMAction]` (`:959-962`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `--config` | required | Path to `simulation_config.json`. Its directory becomes `simulation_dir` | `backend/scripts/run_twitter_simulation.py:1045-1050,715` |
| `--max-rounds` | None | Truncates `total_rounds` when > 0. 0 or negative means no limit. The runner passes it whenever `max_rounds>0`, including in calendar mode, where the runner itself ignores it | `backend/scripts/run_twitter_simulation.py:1051-1057,833-837`; `backend/app/services/simulation_runner.py:916-918,817-823` |
| `--no-wait` | False | Skip the IPC wait loop and close the env right after `simulation_end` | `backend/scripts/run_twitter_simulation.py:1058-1063,1007` |
| `time_config.total_simulation_hours` / `minutes_per_round` | 72 / 60 | `total_rounds = hours*60 // minutes` | `backend/scripts/run_twitter_simulation.py:826-830` |
| `time_config.agents_per_hour_min/max` | 5 / 20 | Range for the activation target | `backend/scripts/run_twitter_simulation.py:763-764` |
| `time_config.peak_hours` / `off_peak_hours` | `[9,10,11,14,15,20,21,22]` / `[0..5]` | Hour multipliers | `backend/scripts/run_twitter_simulation.py:767-768` |
| `time_config.peak_activity_multiplier` / `off_peak_activity_multiplier` | 1.5 / 0.3 | Scales the activation target | `backend/scripts/run_twitter_simulation.py:771,773` |
| `agent_configs[].active_hours` / `activity_level` | `range(8,23)` / 0.5 | Per-agent hour gate and activation probability | `backend/scripts/run_twitter_simulation.py:783-784` |
| `LLM_PROVIDER` (env) → `config.llm_provider` → `Config.LLM_PROVIDER` | `claude-cli` | Picks the CLI bridge or the openai-compat model | `backend/app/utils/oasis_llm.py:481-487,557-584` |
| `LLM_BOOST_API_KEY` / `LLM_BOOST_BASE_URL` / `LLM_BOOST_MODEL_NAME` | unset | Reddit script only (`use_boost=True`), openai-compat path: alternate key/model | `backend/app/utils/oasis_llm.py:495-506`; `backend/scripts/run_reddit_simulation.py:748` |
| `OASIS_CLI_SEMAPHORE` / `OASIS_SEMAPHORE` | 8 / 30 | OASIS concurrency. Single-platform scripts take the whole cap because `platforms=1` | `backend/app/utils/oasis_llm.py:29-30,603-616`; `backend/scripts/run_twitter_simulation.py:876` |
| `SIM_CLI_TOOL_EMULATION` | true | Without it, CLI-bridge agents cannot emit tool calls (hollow sim) | `backend/app/utils/oasis_llm.py:60-62,572-578` |
| `SIM_LLM_FALLBACK` | true | Failover wrapper on the openai-compat path | `backend/app/utils/oasis_llm.py:65-67,599` |
| `PYTHONUTF8`, `PYTHONIOENCODING` | set by runner | UTF-8 I/O in the child | `backend/app/services/simulation_runner.py:930-931` |
| `SIM_SEED`, `SIM_RESUME`, `SIM_START_HOUR`, `SIM_IDLE_CLOSE_MIN`, other `SIM_*` | — | **Ignored** by the single-platform scripts. They are read only by `run_parallel_simulation.py` | e.g. `backend/scripts/run_parallel_simulation.py:102-117,1772-1782,6049-6052` |

---

## External calls

- **LLM.** All LLM traffic goes through OASIS/camel `env.step(...)`. That covers `LLMAction` per active agent per round (`backend/scripts/run_twitter_simulation.py:959-966`) and `ManualAction(INTERVIEW)` (`:233-240, :273-286`), which OASIS routes to `agent.perform_interview` (`backend/.venv/lib/python3.12/site-packages/oasis/environment/env.py:157-187`). The model object comes from `create_oasis_model` (CLI bridge or openai-compat) (`backend/app/utils/oasis_llm.py:557-600`). Seed `CREATE_POST` actions are `ManualAction`s and make no LLM call (`backend/scripts/run_twitter_simulation.py:912-915,928-929`).
- **SQLite.** OASIS owns the DB. These scripts open it read-only (in practice) through `sqlite3.connect` per fetch or interview (`:321, :452`).
- **Filesystem IPC.** Covered above. There is no network, no HTTP and no subprocess spawned by the scripts themselves. The runner spawns them (`backend/app/services/simulation_runner.py:943-953`).
- **Process-level.** dotenv `.env` read (`:40-47`); `signal.signal` (`:1104-1105`).

---

## Cross-module edges

**Callers into this slice:**
- `SimulationRunner.start_simulation` launches the scripts by path for `platform in {"twitter","reddit"}` (`backend/app/services/simulation_runner.py:875-882,888-891`). Script names are also used to verify process identity in orphan cleanup (`backend/app/services/simulation_runner.py:1419-1423`).
- `POST /api/simulation/start` is the only in-app trigger that can select a single platform (`backend/app/api/simulation.py:1538,1640-1646`).
- `SimulationManager.get_run_instructions` (CLI strings, `backend/app/services/simulation_manager.py:1531-1541`) is surfaced by `GET /api/simulation/<id>` (`backend/app/api/simulation.py:806-808`).
- The script download endpoint (`backend/app/api/simulation.py:1359-1400`).
- `action_logger` importers: `backend/scripts/run_parallel_simulation.py:190` (main path), both single-platform scripts (`:138`), and the tests `backend/tests/test_calendar_round_loop.py:34,245` and `backend/tests/test_sim_reaction_phase.py:34,297,471`.
- The only test touching the single-platform scripts is a source scan asserting `--max-rounds` has `default=None` (`backend/tests/test_audit_fixes_runloop.py:91-102`). No behavioural test exercises them.

**Outbound edges:**
- `app.utils.oasis_llm.create_oasis_model` / `get_oasis_semaphore` (`backend/scripts/run_twitter_simulation.py:118,740,876`).
- `oasis.make`, `generate_*_agent_graph`, `env.reset`, `env.step`, `env.close`, `agent_graph.get_agent` / `get_agents` (`:858-879, :928-966, :1037`).
- `action_logger.PlatformActionLogger` (`:138,888`).

**Downstream consumers of the files these scripts write:**
- `SimulationRunner._read_action_log` / `_monitor_simulation` (`backend/app/services/simulation_runner.py:1012-1295`);
- `get_all_actions` (`backend/app/services/simulation_runner.py:1802-1857`);
- the orchestrator's `simulation_end` tail probes (`backend/app/services/pipeline_orchestrator.py:7490-7500,9943-9975`), which only matter on parallel runs;
- `SimulationIPCClient` (`backend/app/services/simulation_ipc.py:209-439`);
- `zep_tools` interview parsing, which expects `twitter_<i>`/`reddit_<i>` keys (`backend/app/services/zep_tools.py:2085-2097`);
- the demo exporter `export_forum` (`backend/scripts/export_demo_site_data.py:580`).

---

## Invariants, gates, validation

- **Balanced round events.** Every `round_start(r)` is paired with exactly one `round_end(r)` on all three paths: empty round, failed step and normal round (`backend/scripts/run_twitter_simulation.py:946,955,970,986`). Round 0 is likewise bracketed (`:903,933`).
- **`simulation_end` is the completion proof.** It is written only after the loop finishes (`:998`). The runner marks a platform complete only on this record (`backend/app/services/simulation_runner.py:1186-1196`). The runner never treats a 0 exit code alone as completion (`backend/app/services/simulation_runner.py:1079-1100`).
- **No double logging of seed posts.** Seed posts are logged by hand, then `last_rowid` is advanced past their trace rows before round 1 (`backend/scripts/run_twitter_simulation.py:917-924,932`).
- **Monotone trace cursor.** `last_rowid` only increases, and filtered rows (`refresh`, `sign_up`) still advance it (`:463-467`).
- **Fresh world each run.** The DB is deleted before `oasis.make` (`:865-868`). The runner rotates the previous `actions.jsonl` to `actions.prev.jsonl` before launch, because single-platform runs never resume (`backend/app/services/simulation_runner.py:773-786,1320-1328`). [verifier: only the runner rotates. The scripts never truncate the file, and `PlatformActionLogger` always opens it with `'a'` (`backend/scripts/action_logger.py:65,81,102,117,130`). A manual CLI rerun, which is one of the reachability paths above, appends a second `simulation_start…simulation_end` sequence to the old file. The fresh DB then sits beside a mixed action log.]
- **Resume gate (runner side).** `resume_requested` is forced False when `platform != "parallel"`, because these scripts' argparse would reject `--resume` with exit 2 (`backend/app/services/simulation_runner.py:773-777`). [verifier: argparse does raise `SystemExit(2)`, but it does so inside `asyncio.run(main())` (`backend/scripts/run_twitter_simulation.py:1065,1111`). `__main__` swallows it with `except SystemExit: pass` (`:1114-1115`), so the process actually exits **0**. I reproduced this with the backend venv Python 3.12.6 on a copy of the same `__main__` pattern: an unknown `--resume` printed the usage error and returned rc=0. LOOP-001 would still mark the run FAILED because no `simulation_end` is written (`backend/app/services/simulation_runner.py:1089-1101`). The runner comment at `:773-774` is stale.]
- **Interview gate.** The client requires `env_status == "alive"`. The scripts write `alive` only after `simulation_end` and only in wait mode (`backend/scripts/run_twitter_simulation.py:1013`; `backend/app/services/simulation_ipc.py:437`).
- **Config validation.** Only the existence of the config file is checked (`:1071-1073`) and the profile file (`:853-856`). There is no schema, seal or agent-id alignment check in the child; parallel has a soft check (`backend/scripts/run_parallel_simulation.py:5893-5906`). The runner does the LOOP-011 manifest checks before spawning (`backend/app/services/simulation_runner.py:493-757`).

---

## Failure modes & recovery

| Failure | Behaviour | Anchor |
|---|---|---|
| `oasis`/`camel` not importable | prints a hint and exits with code 1 (module level) | `backend/scripts/run_twitter_simulation.py:130-133` |
| Config file missing | `sys.exit(1)` inside `main()`, but `__main__` swallows `SystemExit`, so the **exit code is 0**. The runner still marks FAILED because no `simulation_end` was written [verifier: argparse errors also exit 0, for example an unknown `--resume`/`--config-seal` or a missing `--config` flag. `parse_args` runs inside the same swallowed `asyncio.run` (`backend/scripts/run_twitter_simulation.py:1065,1114-1115`).] | `backend/scripts/run_twitter_simulation.py:1071-1073,1114-1115`; `backend/app/services/simulation_runner.py:1089-1100` |
| Profile file missing | `run()` returns with exit 0, no actions file and no `env_status` → runner FAILED (LOOP-001 message) | `backend/scripts/run_twitter_simulation.py:853-856`; `backend/app/services/simulation_runner.py:1089-1100` |
| Exception in model/graph creation, `env.reset` or the **seed-post `env.step`** | uncaught, so the process dies with a traceback (exit 1) → runner FAILED with the log tail. `env_status` stays `running` until the runner's `_mark_env_stopped` [verifier: this is true only for the seed-step failure. Model/graph creation and `env.reset` run before `IPCHandler` exists (`backend/scripts/run_twitter_simulation.py:849-879` vs `:883-884`), so in those cases this run writes no `env_status.json` at all. In addition, the seed `CREATE_POST` lines are already in `actions.jsonl` before the step that raises (`:917` vs `:929`).] | `backend/scripts/run_twitter_simulation.py:849-879,928-929`; `backend/app/services/simulation_runner.py:1101-1112` |
| `env.step` raises in a round | logged by print, `round_end(r,0)`, continue. Repeats without limit, with no breaker | `backend/scripts/run_twitter_simulation.py:965-971` |
| A single agent's LLM error inside `env.step` | OASIS gathers the tasks, so a raise propagates as above. Errors OASIS swallows per agent simply yield 0 trace rows (an empty round) and are not counted. Parallel counts them in `llm_health.json` | `backend/.venv/lib/python3.12/site-packages/oasis/environment/env.py:193`; `backend/scripts/run_parallel_simulation.py:2231-2269,2270` |
| DB read error in `fetch_new_actions_from_db` / enrichment | printed and swallowed. The round logs fewer actions | `backend/scripts/run_twitter_simulation.py:498-499,595-597,629-630` |
| Interview error / unknown command | `"failed"` response with the error string | `backend/scripts/run_twitter_simulation.py:249-253,301-305,387-389` |
| Client times out an interview | the child still runs the interview LLM call and writes an orphan response, because it does not check `.cancel`. The client's stale sweep removes it later | `backend/scripts/run_twitter_simulation.py:200-219`; `backend/app/services/simulation_ipc.py:231-236,323-333` |
| SIGTERM during the round loop | event set but not checked, so the loop continues. The runner sends SIGKILL after 10 s and the runner-side post-exit handling marks STOPPED/FAILED | `backend/scripts/run_twitter_simulation.py:939-995,1091-1098`; `backend/app/services/simulation_runner.py:1653-1662` |
| SIGTERM in the wait loop | loop exits within 0.5 s, `stopped` is written, env closes, `finally` prints | `backend/scripts/run_twitter_simulation.py:1017-1037` |
| Backend restart while the child lives | orphan reaping identifies the child by script name | `backend/app/services/simulation_runner.py:1419-1423` |

---

## Surprises

1. **The single-platform scripts are unreachable from the product flow.** The orchestrator always sends `platform="parallel"` (`backend/app/services/pipeline_orchestrator.py:8800,12975`). The only UI wrapper `startSimulation` (`frontend/src/api/simulation.js:86-87`) has no callers. Only raw HTTP, the CLI instructions and the download endpoint reach these scripts. They are kept but effectively legacy (`drf2/CLEANUP_LOCAL.md:23-27`). [verifier: imprecise. The enabled DRF-2 simulation MCP tool `sim_start` also accepts `platform="twitter"|"reddit"` and forwards it to `SimulationRunner.start_simulation` (`drf2/engines/simulation/server.py:61-96`; `drf2/engines/simulation/jobs.py:158-185`; `drf2/config/extensions_config.json:20-27`).]
2. **About 300 lines are duplicated three ways.** `FILTERED_ACTIONS`, `ACTION_TYPE_MAP`, `get_agent_names_from_config`, `fetch_new_actions_from_db`, `_enrich_action_context`, `_get_post_info`, `_get_user_name` and `_get_comment_info` appear functionally identically in both single scripts (`backend/scripts/run_twitter_simulation.py:392-689`; `backend/scripts/run_reddit_simulation.py:392-689`) and in parallel (`backend/scripts/run_parallel_simulation.py:1349-1721`). The two single scripts are about 99% the same file (see the diff table). Any fix must land in 3 places.
3. **Suspected: the Twitter seed-post overwrite bug is unfixed here.**
   - Several `initial_posts` from the same `poster_agent_id` overwrite each other in a dict, so only the last post is executed (`backend/scripts/run_twitter_simulation.py:912-915`).
   - Every one of them is still written to `actions.jsonl` as round-0 `CREATE_POST` (`:917-924`), so the log claims posts that never happened.
   - Parallel fixed exactly this with a list merge (`backend/scripts/run_parallel_simulation.py:4869-4881`), and the Reddit single script has the list merge (`backend/scripts/run_reddit_simulation.py:898-909`).
4. **Suspected: the round-0 `actions_count` is wrong.** It is `len(initial_posts)` (`backend/scripts/run_twitter_simulation.py:933`), which includes posts whose agent failed to resolve and so were never logged (`:925-926`). Parallel uses a real counter, `initial_action_count` (`backend/scripts/run_parallel_simulation.py:4861,4937`).
5. **`simulated_hours` is never emitted, so the runner's simulated time stays 0 for single-platform runs.** The runner stores `action_data.get("simulated_hours", 0)` from `round_end` (`backend/app/services/simulation_runner.py:1226,1236-1247`). The scripts call `log_round_end(r, n)` without it (`backend/scripts/run_twitter_simulation.py:955,970,986`). The logger docstring itself warns about this (`backend/scripts/action_logger.py:87-89`).
6. **Suspected: in calendar mode, a single-platform run silently loses calendar semantics.**
   - The scripts ignore `temporal_config`. They rely on the compatibility shim `total_simulation_hours = n_rounds, minutes_per_round = 60` (`backend/app/services/simulation_config_generator.py:577-581`) for the round count, but drive activation by `hour = round % 24` (`backend/scripts/run_twitter_simulation.py:942`). With default `active_hours=range(8,23)`, rounds whose index mod 24 falls in 0-7 have no candidates, so the first 8 of every 24 are dead. [verifier: miscounted. `range(8,23)` also excludes hour 23 (`backend/scripts/run_twitter_simulation.py:783,787`), so 9 of every 24 rounds (hours 0-7 and 23) are dead under that fallback. In practice the generated `agent_configs` usually carry explicit `active_hours` (for example `range(9,23)`, `range(9,18)` or `range(7,24)` at `backend/app/services/simulation_config_generator.py:3040,3666-3789,3980`), so the dead fraction depends on the cast.]
   - They also honour `--max-rounds`, which the runner deliberately ignores in calendar mode (`backend/app/services/simulation_runner.py:817-823` vs `:916-918`). The child may therefore stop early while `run_state.total_rounds` = n_rounds, and the run still completes via `simulation_end`.
7. **Suspected: batch-interview results have a different shape from what the report reads.**
   - Single scripts key results by bare `agent_id` (`backend/scripts/run_twitter_simulation.py:289-297`).
   - `ZepToolsService` looks up `results_dict.get(f"twitter_{idx}")` / `f"reddit_{idx}"` (`backend/app/services/zep_tools.py:2096-2097`).
   - So report interviews against a single-platform run would read empty responses ("（该平台未获得回复）", no reply received from this platform). The parallel handler emits `twitter_<id>`/`reddit_<id>` (`backend/scripts/run_parallel_simulation.py:1134,1161`).
8. **Suspected: the MUTE and CREATE_COMMENT enrichment branches are dead under camel-oasis 0.2.5. This affects parallel too.**
   - OASIS records mute as `{"mutee_id"}` (`backend/.venv/lib/python3.12/site-packages/oasis/social_platform/platform.py:996`). The key-filter drops `mutee_id` (`backend/scripts/run_twitter_simulation.py:477-482`), and the enrichment looks for `user_id`/`target_id` (`:571`). The mute target is lost entirely.
   - OASIS records create_comment as `{"content","comment_id"}` with no `post_id` (`.../oasis/social_platform/platform.py:1104`). The `CREATE_COMMENT` branch (`backend/scripts/run_twitter_simulation.py:587-593`) therefore never adds the parent post.
9. **Suspected: `SimulationLogManager` and the runner open the same `simulation.log` twice, which can clobber it (parallel path).**
   - The runner opens `simulation.log` with `'w'` and hands it to the child as stdout/stderr (`backend/app/services/simulation_runner.py:924-925,943-947`).
   - The child's `SimulationLogManager` opens the same path again with `FileHandler(mode='w')` (`backend/scripts/action_logger.py:157,165`), which truncates it. It also writes each record a second time through a stderr `StreamHandler` (`:174-180`).
   - Two non-append file descriptors with independent offsets on one inode can overwrite each other's bytes or leave NUL gaps.
   - This only affects the parallel script. The single scripts only `print`.
10. **Suspected: the root-logger `MaxTokensWarningFilter` is probably ineffective.** Python applies logger-level filters only to records created on that logger, not to records propagated from children such as camel's module loggers (`backend/scripts/run_twitter_simulation.py:81`). The same pattern appears in parallel (`backend/scripts/run_parallel_simulation.py:138-149`). [verifier: refuted. The only "Invalid or missing `max_tokens`" message in the installed camel is emitted with the module-level `logging.warning(...)`, which logs on the root logger itself (`backend/.venv/lib/python3.12/site-packages/camel/types/unified_model_type.py:67-70`). Root's own filters therefore apply and the filter does drop it. The propagation caveat is true in general, but no child logger emits this message.]
11. **Dead code in `action_logger.py`.** `ActionLogger` and `get_logger` (`backend/scripts/action_logger.py:214-323`) have no importers. They still carry the stale `hours*2` total-rounds formula (`:289`) that `PlatformActionLogger` explicitly fixed (`:106-108`). Also unused:
    - `IPCHandler._running` (`backend/scripts/run_twitter_simulation.py:163`);
    - `ModelFactory`/`ModelPlatformType` imports (`:121-122`);
    - the `round_num` parameter of `_get_active_agents_for_round` (`:746`);
    - `SimulationLogManager.debug` (`backend/scripts/action_logger.py:210-211`), which is a no-op because the logger level is INFO (`:161`).
12. **`sys.exit(1)` becomes exit code 0.** `except SystemExit: pass` in `__main__` (`backend/scripts/run_twitter_simulation.py:1114-1115`) masks the missing-config exit (`:1073`). The second-signal `sys.exit(1)` (`:1102`) is masked the same way. The runner's LOOP-001 rule (no `simulation_end` means FAILED) is what saves correctness (`backend/app/services/simulation_runner.py:1089-1100`).
13. **No idle timeout in wait mode.** A single-platform child waits for IPC forever unless `close_env`, a signal or a backend cleanup arrives (`backend/scripts/run_twitter_simulation.py:1016-1025`). Parallel auto-closes after `SIM_IDLE_CLOSE_MIN` (default 60) (`backend/scripts/run_parallel_simulation.py:6046-6066`). The runner already marks COMPLETED at `simulation_end` (`backend/app/services/simulation_runner.py:1203-1211`), so the lingering process holds the DB and memory indefinitely.
14. **Reddit OASIS logging config names `social.twitter`.** The list is copy-pasted and there is no `social.reddit` logger (`backend/scripts/run_reddit_simulation.py:99-105`). [verifier: the copy-paste is real, but it is not a defect. OASIS's shared `Platform` module logs to `social.twitter` for both platforms (`backend/.venv/lib/python3.12/site-packages/oasis/social_platform/platform.py:42`). OASIS defines no `social.reddit` logger, so `social.twitter` is the correct logger to configure for Reddit too.]
15. **Code comments overstate the runner's role.** The F-9-0 comment says the runner "generates run_summary and exports forum" on `simulation_end` (`backend/scripts/run_twitter_simulation.py:135-137`; `backend/scripts/run_reddit_simulation.py:135-137`). In fact `write_run_summary` is called only by the orchestrator (`backend/app/services/pipeline_orchestrator.py:8864,10108`), which never runs single-platform, and "forum" export exists only in the demo-site exporter (`backend/scripts/export_demo_site_data.py:580`). An API-started single-platform run gets no `run_summary.json`. [verifier: "only by the orchestrator" is wrong. `SimulationJobService.results` also calls `SimulationRunner.write_run_summary(sim_id)` when a terminal job has no summary (`drf2/engines/simulation/jobs.py:328-332`). A single-platform run started through DRF-2 `sim_start` can therefore get a `run_summary.json`. The forum part is confirmed: no `forum` reference exists in `backend/app`.]
16. **Doc-vs-code drift:**
    - `drf2/CLEANUP_LOCAL.md:24-25` cites the runner's twitter/reddit branches at "lines ~537/541". They are now at `backend/app/services/simulation_runner.py:875,879`.
    - `ARCHITECTURE_MAP.md:37` cites the Popen at `simulation_runner.py:685-695`. It is at `:943-953`.
    - `docs/architecture/DEEPRESEARCHFORECAST_SYSTEM_ATLAS.md:708` places the canonical loops at `run_parallel_simulation.py:3547-4715`. They are at `:4692` and `:5228`.
    - `ARCHITECTURE.md:60-65` lists the single-platform scripts alongside parallel without noting that they are a reduced, unused code path.
17. **Stdout buffering (suspected minor).** The scripts report only through `print()` to a file-backed stdout. Without `PYTHONUNBUFFERED` or `flush=True`, output is block-buffered, so `simulation.log` lags and loses its tail on SIGKILL. The runner reads that tail for its FAILED error text (`backend/app/services/simulation_runner.py:1087-1088`).

---

## Verification

Adversarial pass on 2026-10-11 against the `main` checkout on disk. Every cited anchor was opened. The checks were read-only: grep, sed and an AST comparison of the duplicated helpers. One extra probe ran a copy of the scripts' `__main__` pattern under the backend venv's Python 3.12.6, in the session scratchpad and not in the repo. The 14 inline `[verifier: …]` notes above mark each correction in place.

**Verdict counts (27 key claims and surprises, plus 4 extra spot-check findings):**

| Group | Confirmed | Imprecise | Refuted | Unverifiable |
|---|---|---|---|---|
| Key claims (14) | 13 | 1 | 0 | 0 |
| Surprises (13) | 9 | 3 | 1 | 0 |
| Extra spot-check findings (4, not counted above) | — | 4 | 0 | 0 |

**Spot-checks that held up.** More than 10 Walkthrough and Control-flow statements were checked and found correct:
- the 2 s monitor tail (`backend/app/services/simulation_runner.py:1029-1046`);
- the `log_action` caller list and the fact that no caller passes `result`/`success`;
- the legacy root `actions.jsonl` fallback (`backend/app/services/simulation_runner.py:1845-1855`);
- the helpers being functional copies of parallel (an AST compare without docstrings shows only `fetch_new_actions_from_db` differs, and only in its key-copy loop style);
- the Twitter (6) and Reddit (13) action lists versus parallel `TWITTER_ACTIONS`/`REDDIT_ACTIONS` (`backend/scripts/run_parallel_simulation.py:214-241`);
- the early `return` on a missing profile, which happens before the logger, env and IPC handler exist;
- the `last_rowid` advance past the seed rows;
- the signal-handler semantics;
- the parallel `asyncio.gather(..., return_exceptions=True)` and `--twitter-only`/`--reddit-only` dispatch;
- the runner start sequence (`backend/app/services/simulation_runner.py:474-975`);
- COMPLETED being set at `simulation_end` and the post-exit LOOP-001 reconciliation;
- the `LLM_PROVIDER` default `claude-cli` (`backend/app/config.py:750`);
- the semaphore defaults 8 and 30 (`backend/app/utils/oasis_llm.py:29-30`).

**Non-confirmed items and corrections:**
1. *Claim: the runner forces resume off because single-platform argparse "would exit 2"* — **imprecise**. argparse raises `SystemExit(2)` inside `asyncio.run(main())`, and `__main__` swallows it, so the process exits **0** (`backend/scripts/run_twitter_simulation.py:1065,1111,1114-1115`). Reproduced: rc=0. The runner comment at `backend/app/services/simulation_runner.py:773-774` is stale. The FAILED verdict still comes from LOOP-001 (`:1089-1101`).
2. *Surprise: single-platform scripts unreachable from the product flow, reached only via the API, CLI and download* — **imprecise**. The enabled DRF-2 MCP tool `sim_start` accepts `platform="twitter"|"reddit"` and forwards it to `SimulationRunner.start_simulation` (`drf2/engines/simulation/server.py:61-96`; `drf2/engines/simulation/jobs.py:158-185`; `drf2/config/extensions_config.json:20-27`). The orchestrator part is confirmed (`backend/app/services/pipeline_orchestrator.py:8800,12975`).
3. *Surprise: calendar mode makes "the first 8 of every 24" rounds dead* — **imprecise**. The `range(8,23)` fallback excludes hours 0-7 **and 23**, so 9 of every 24 rounds are dead (`backend/scripts/run_twitter_simulation.py:783,787`). Generated configs normally set explicit `active_hours` (`backend/app/services/simulation_config_generator.py:3040,3666-3789,3980`), so the dead fraction depends on the cast. The `--max-rounds` part is confirmed (`backend/app/services/simulation_runner.py:817-823,916-917`).
4. *Surprise: `MaxTokensWarningFilter` on the root logger is likely ineffective* — **refuted**. camel emits that warning with module-level `logging.warning(...)` on the root logger (`backend/.venv/lib/python3.12/site-packages/camel/types/unified_model_type.py:67-70`), so the root filter applies.
5. *Surprise: F-9-0 comments overstate the runner; `write_run_summary` is called only by the orchestrator* — **imprecise**. `drf2/engines/simulation/jobs.py:328-332` also calls `SimulationRunner.write_run_summary` for terminal jobs that have no summary. The forum-export part is confirmed (`backend/scripts/export_demo_site_data.py:580`; no `forum` reference in `backend/app`).
6. *Surprise: the Reddit OASIS log setup configures `social.twitter` (copy-paste)* — **imprecise**. This is literally true but not a defect. OASIS's shared `Platform` logs to `social.twitter` for both platforms (`backend/.venv/lib/python3.12/site-packages/oasis/social_platform/platform.py:42`). The DEBUG-versus-disabled contrast with parallel is confirmed (`backend/scripts/run_parallel_simulation.py:152-185`).
7. *Walkthrough step 10: "Prints progress at round 1 and every 10 rounds"* — **imprecise**. It is skipped on empty or failed rounds, which `continue` first (`backend/scripts/run_twitter_simulation.py:956,971`).
8. *Walkthrough step 13: "Always writes `env_status=stopped` and calls `env.close()`"* — **imprecise**. These calls are not in a `finally` and are skipped if `run()` raises earlier (`backend/scripts/run_twitter_simulation.py:928-929,1036-1037`).
9. *Control flow 5: "The client refuses unless env_status == alive"* — **imprecise**. `send_command` does not check it (`backend/app/services/simulation_ipc.py:209-342`). The callers gate on `check_env_alive()` (`backend/app/services/simulation_runner.py:2683,2772,2888`; `backend/app/api/simulation.py:2383,2518`; `backend/app/mcp/sim_server.py:98`).
10. *Failure modes: a model/graph/`env.reset` exception leaves "`env_status` running"* — **imprecise**. `IPCHandler` is built only after `env.reset` (`backend/scripts/run_twitter_simulation.py:879,883-884`), so in those cases this run writes no `env_status.json`. Only a seed-step failure leaves `running`.

Notes on confirmed items:
- Claim 10 (the stop path): the 10 s SIGTERM→SIGKILL window applies to `stop_simulation`. Server-shutdown cleanup uses 5 s (`backend/app/services/simulation_runner.py:2442`).
- Claim 13 (use_boost): it is literally correct, but `get_oasis_semaphore` ignores `use_boost` entirely (`backend/app/utils/oasis_llm.py:603-616`).

**Omissions (significant behaviour the map did not cover):**
- **Manual CLI reruns append to a stale action log.** Only the runner rotates `actions.jsonl` (`backend/app/services/simulation_runner.py:783-784,1310-1337`). The scripts always append (`backend/scripts/action_logger.py:65,81,102,117,130`), so a CLI rerun stacks a second `simulation_start…simulation_end` run onto the old file, beside a freshly deleted and rebuilt DB (`backend/scripts/run_twitter_simulation.py:865-868`).
- **DRF-2 is a second launcher and a second `run_summary` writer.** `sim_start` can choose a single platform (`drf2/engines/simulation/server.py:61-96`), and `results()` runs `write_run_summary` for terminal jobs (`drf2/engines/simulation/jobs.py:328-332`).
- **Every argparse failure exits 0,** not only the missing-config `sys.exit(1)`. This covers an unknown flag such as `--resume`/`--config-seal` and a missing `--config` (`backend/scripts/run_twitter_simulation.py:1065,1114-1115`).
- **Seed posts are logged before they execute.** The round-0 `CREATE_POST` lines are written before the unguarded seed `env.step` (`backend/scripts/run_twitter_simulation.py:917` vs `:929`). If that step raises, `actions.jsonl` claims posts that never happened and has no `round_end(0)` or `simulation_end`.
- **`use_boost` is a no-op for the semaphore** (`backend/app/utils/oasis_llm.py:603-616`). Both scripts get the same cap. Boost changes only the openai-compatible model credentials (`backend/app/utils/oasis_llm.py:490-506`).
- **The stop API cannot kill a lingering wait-mode child.** After `simulation_end` the runner status is COMPLETED, and `stop_simulation` rejects any status other than RUNNING, PAUSED or STARTING (`backend/app/services/simulation_runner.py:1673-1674`). Combined with the missing idle timeout, only `close_env` (`backend/app/services/simulation_runner.py:2865-2900`), server cleanup (`:2391-2450`) or orphan reaping can end the child.
