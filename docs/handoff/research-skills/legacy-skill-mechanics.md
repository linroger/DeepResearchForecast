# Legacy engine: how skills reach the model (Explore agent, 2026-10-16)

I traced the full path for the legacy engine. In short, a new skill folder deploys on its own, but the lead agent only sees it after you add its name to a hardcoded set in `deerflow_research.py`. The scoped-researcher subagent only gets it after you add it to `deer-flow/config.yaml`, and that file is not synced automatically.

## 1. Discovery and deployment

- **Sync helper:** `deerflow_bridge/runtime_skill_sync.py` deploys every folder under `deerflow_bridge/skills/` that contains a regular `SKILL.md` (`_discover_source_manifests`, :186-197). There is no allowlist for deployment.
- **`DEFAULT_REQUIRED_SKILLS` (:47-54):** the six current names. This is only a fail-closed minimum ("required runtime skill source bundle(s) missing", :427-431). Add a name there only if a missing folder should block launch.
- **Manifest:** each folder gets a sha256 manifest (:110-169). `lazy_resource_hashes` covers every file except `SKILL.md`. The installed state is written to `deer-flow/skills/public/.drf-runtime-skill-manifest.json`, which currently lists exactly the six skills.
- **How it deploys:** a full `skills/public` tree is staged, verified, then atomically swapped in (:455-490). Skills that disappear from the source are pruned (:438-439). Upstream DeerFlow skills are kept, except any with the same name as a bridge skill, which the bridge copy replaces (:288).
- **Filtering and failure modes:**
  - `__pycache__/`, `logs/`, `.claude/`, `.DS_Store` and `*.pyc` are skipped (:65-67).
  - A symlink, or a folder name not matching `^[A-Za-z0-9][A-Za-z0-9._-]*$`, raises an error and blocks every research launch (:63, :129-145).
- **Callers:**
  - The orchestrator runs it before every research child: `_RUNTIME_SKILL_SYNC_HELPER_PATH` at `backend/app/services/pipeline_orchestrator.py:1349`, the call at :1552-1556, and the "Runtime skill bundle %s … lazy_resource_hashes=%s" log at :1562-1574.
  - It passes the result to the child as `DRF_RUNTIME_SKILL_SYNC` (:2372-2383). The child re-hashes the deployed tree in `runtime_skill_sync_telemetry` (`deerflow_research.py:480-515`).
  - `setup.sh:635-648` runs the same helper.
- **Tests that pin the skill set:**
  - `backend/tests/test_runtime_skill_sync.py:364-380` pins the exact six-name tuple.
  - Temp-repo fixtures hardcode the six names: `test_deerflow_bridge_sync_guard.py:36-45`, `test_data_sources_config.py:43-46`, `test_bridge_extensions_config.py:35-37`.
  - `test_drf2_skills_config.py:653-683` checks that committed bridge skill files match the deployed copies byte for byte. Once you commit a skill, the deployed tree must be re-synced or this test fails.

## 2. Enablement

There are three layers, and a skill must pass all of them:

1. **Global enabled state.**
   - `load_skills` reads frontmatter, keys skills by the frontmatter `name` (`skill_storage.py:227`), then applies `ExtensionsConfig.is_skill_enabled`.
   - A skill with no entry is enabled if it is public or custom (`config/extensions_config.py:221-224`).
   - The bridge's `extensions_config.json` has `"skills": {}`, so every skill is enabled. Nothing to change here.
2. **Lead-agent whitelist.**
   - The legacy engine builds `DeerFlowClient(..., available_skills={"deep-research","actor-ontology-research","prediction-markets","forecast-visuals","data-sources","data-visuals"})` at `deerflow_research.py:18029-18045`.
   - **This is the hardcoded list your new names must join.** No test pins it.
   - Semantics: `None` means all enabled skills; a set means only those (`client.py:146`). The `config.yaml` `skills:` block only sets `container_path: /mnt/skills` (`deerflow_bridge/config.yaml:1280-1290`).
3. **Subagent whitelist.**
   - `subagents.custom_agents.scoped-researcher.skills` is `[deep-research, prediction-markets, data-sources]` (`config.yaml:1239-1242`).
   - Semantics: `None` loads all enabled skills, `[]` loads none, a list loads only those (`subagents/executor.py:409-433`). A `subagents.agents.scoped-researcher.skills` override would take precedence (`subagents/registry.py:107-111`); there isn't one today.
   - At runtime, `_register_legacy_data_tools` appends `data-sources` to this list if missing (`deerflow_research.py:5141-5146`).
   - In the embedded-client path the subagent list is not intersected with the lead's list. Only `make_lead_agent` writes `metadata["available_skills"]` (`agent.py:485`), and `task_tool.py:279-281` needs that key to merge them.

`deer-flow/config.yaml` is currently identical to the bridge copy. However, it is never overwritten automatically: `setup.sh:711-720` skips an existing file, and the orchestrator only logs a drift warning (`pipeline_orchestrator.py:1781-1792`). The research child runs with `cwd=deer-flow` (:2498), so it reads the deployed copy.

## 3. How the model sees a skill

- **Lead agent, metadata only:**
  - `get_skills_prompt_section` (`agents/lead_agent/prompt.py:604-670`) renders `<skill_system>` with an `<available_skills>` list of `<skill><name>…<description>…<location>/mnt/skills/public/<dir>/SKILL.md</location>`.
  - It tells the model to "immediately call `read_file` on the skill's main file" when a query matches. Discovery therefore depends entirely on the description.
  - The description is not escaped (:614).
  - The `/mnt/skills` path maps to `deer-flow/skills` (`sandbox/tools.py:140-163`).
- **Lead agent, slash activation:**
  - `SkillActivationMiddleware` (`skill_activation_middleware.py:66-260`) checks the latest user message for `^/name` (`skills/slash.py:9`).
  - It injects the whole `SKILL.md`, escaped, into every model request of that turn. This is a request override and is not stored in state.
  - If the name is not whitelisted, the turn short-circuits with "Skill `/x` is not available for this agent." (:110-111).
  - Every legacy pass prompt starts with `/deep-research\n` (`deerflow_research.py:5425, 5450, 5495, 5578, 5656, 5695, 11051, 11093, 12162, 12861`). Track B uses `/actor-ontology-research\n` (13812, 13937, 14692).
  - Only one slash skill fits per message. Any other skill must be read with `read_file`, either by the model on its own or because the prompt says so. The existing example is `_official_data_prompt_block`: "read_file of /mnt/skills/public/data-sources/SKILL.md is permitted" (:5184).
  - The scripts in `data-visuals` and `forecast-visuals` are run directly by the bridge (:16727, 17065), not by the model.
- **Subagent:** the full `SKILL.md` of every whitelisted skill goes into the system prompt as `<skill name=…>` (`executor.py:438-507`). There is no size cap.
- **Size caps:** only on summarization, which keeps recent `read_file` skill reads under `/mnt/skills`: count 3, 15,000 tokens total, 5,000 per skill (`config.yaml:1385-1396`; selection logic at `patches/middlewares/summarization_middleware.py:452-478`). A skill file over 5k tokens that was read via `read_file` is never kept. The "~5 skills / ~25k tokens" in the comment describes Claude Code, not these settings.

## 4. Bridge patches

`apply_lead_agent_overlays.py`, `apply_subagent_overlays.py` and `apply_model_factory_overlays.py` don't change skill handling: they cover summary trimming, model inheritance and subagent failure contracts. The only skill-aware patch is the summarization rescue described above.

## 5. Format and size limits

- **Parser** (`skills/parser.py:85-115`):
  - Requires a leading `---\n…\n---\n` block with non-empty string `name` and `description`; otherwise the skill is silently dropped.
  - Optional `allowed-tools` must be a list.
- **Install validator** (`skills/validation.py:15-86`): allowed keys only, `name` hyphen-case and at most 64 characters, `description` at most 1024 characters with no `<` or `>`. Keep to these anyway; the slash regex and the unescaped prompt rely on them.
- **Name rule:** the frontmatter `name` must equal the folder name. The sync is keyed by folder name, the harness and slash activation by frontmatter name.
- **Size and content pins:**
  - deep-research core: `len(core) <= 7000` (`test_loop010_research_contracts.py:241`, `test_legacy_official_data.py:1352`). It is currently **6,996 chars, so only 4 chars of room**.
  - actor-ontology: under 20,000 bytes; currently 19,465 (`test_sessionb_skill_hygiene.py:64-67`).
  - No skill may contain a "deep-research §N" reference; this applies to new skills too (:99-109).
  - The data-visuals frontmatter is pinned by hash (`test_data_visuals_official.py:520-524`).

## Steps for each new skill folder

**(a) Deploy**
1. Create `deerflow_bridge/skills/<name>/SKILL.md` with frontmatter `name: <name>` and a description. Put long material under `references/` (loaded lazily, hash-tracked). No symlinks.
2. Run `./setup.sh` or any orchestrated research run, then commit.
3. Optionally add the name to `DEFAULT_REQUIRED_SKILLS`. If you do, update the pin in `test_runtime_skill_sync.py` and the three fixture tuples listed in section 1.

**(b) Enable**
1. Add the name to the `available_skills` set at `deerflow_research.py:18038`.
2. Add it to `scoped-researcher.skills` in **both** `deerflow_bridge/config.yaml` and `deer-flow/config.yaml`.

**(c) Make it discoverable at the right time**
- Write the description as a trigger condition, since that is all the lead agent sees.
- For a guaranteed load, either name the skill in the prompt with an explicit `read_file /mnt/skills/public/<name>/SKILL.md` line, or build a dedicated pass that starts with `/<name>\n`.
- Don't change the existing builders that start with `/deep-research`: `test_loop010:54` pins that prefix for eight of them.

**(d) Tests**
- Make sure the deployed copy matches the source byte for byte.
- Consider adding tests like `test_sessionb_skill_hygiene` for the new skills' size and headings.

## Pitfalls

- **Engine default:** the backend defaults to `RESEARCH_ENGINE` v3 (`backend/app/config.py:1187`), which uses its own static prompt and never activates skills (`deerflow_research.py:17807-17809`). Only legacy runs, or the `--evidence-only`, `--synthesis-manifest` and `--extract-only` lanes, use skills.
- **Don't declare `allowed-tools`:** once any whitelisted skill declares it, the scoped-researcher's tools shrink to the union of declared lists (`skills/tool_policy.py:13-44`, `executor.py:489`). Leaving out `web_search` would remove it.
- **Subagent cost:** every skill added to scoped-researcher adds its full body to every subagent call. The current three already total about 23.7k chars.
- **Name collisions:** a bridge skill with the same name as an upstream one (e.g. `data-analysis` or `consulting-analysis`) silently replaces it.
- **Prompt cache:** each skill added to the lead whitelist adds about 100 to 150 tokens to the lead system prompt and changes its cached prefix.
