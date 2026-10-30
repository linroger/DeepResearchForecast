# Child research transport spending boundary

**Status:** Owned transport slice and loaded-request scope fix complete and independently reviewed. Coordinator-composed SB-02/SB-12 remains separate. **Scope:** offline code and fake-transport verification only.

## Request and ownership

Implement spending admission at every physical research model invocation and Firecrawl search/scrape POST, while preserving unbound legacy behavior. This owner may edit only `deerflow_bridge/research_gateway.py`, `search_tools.py`, `cached_fetch.py`, `linear_research.py`, `backend/tests/test_run_spending_child_transports.py`, and this document. The shared store belongs to Franklin (`01a18596-3fca-7453-959e-0db48b1bb285`). No provider/network/paid/scheduler/deployment/primary writes or commit/push are authorized. Other owners' work is preserved.

## Requirements and acceptance

| Requirement | Real production path exercised with fake transport | Expected evidence |
|---|---|---|
| Every physical model attempt reserves the complete maximum | `ModelGateway.invoke/json/prime` through `_provider_call` and daemon worker | Same ledger; final output cap including widening; verified route input ceiling; raw usage before estimates |
| Required context and route fail closed | Model factory, gateway, tool entry points, worker missing ContextVar | No client construction/send for invalid route or contract; typed stop propagates |
| One module identity | Package imports plus deployed sibling imports | Identical exception class, binding ContextVar, and store module |
| Firecrawl POSTs retain maxima | Real search and fetch implementations with fake HTTP clients | Each POST has one reservation; 429/ambiguous outcome halts without retry |
| No alternate unpriced dispatch | Model fallback, Serper/Tavily/DDG, Jina/Exa/direct, optional data/news/markets | No fallback transport/client invocation when bound |
| Cached work is free of new dispatch | Positive cache and concurrent singleflight through real tools | One original debit; no follower/cache debit |
| Compatibility | Existing gateway/search/fetch/linear engine tests | Unbound legacy behavior unchanged |
| Loaded request stays within immutable authorization | Bootstrap-checked prompt is rewritten before CLI reread; actual question/args/out-dir reach `linear_research.run` | Fixed control request and full immutable request hash deny before bridge/engine/gateway construction |

## Source trace and plan

1. Read approved PLANS.md, contracts.md and shared handoff. Trace final physical calls and catch boundaries before coding.
2. Obtain the exact core API/schema, required environment/hash contract and one-module import identity from the core owner. Do not implement temporary permissive adapters.
3. Enforce construction-time route admission, final-request reservations, strict retry proof, worker context propagation, typed stop rethrows and closed Firecrawl profile in the four owned sources.
4. Exercise real gateway/tool paths using fake Model/HTTP only under the existing guarded runner. Preserve every failed receipt; use a fresh canonical `/private/tmp` evidence directory per run.
5. Review the owned diff, record exact verification and remaining coordinator dependencies. Do not commit or push.

## Initial source findings and decisions

- `research_gateway._provider_call` is the final `runnable.invoke` seam. `_call_within` already copies context into its daemon thread. Gateway fan-out and the async helper pool currently omit context copying.
- `without_sdk_retries` is intentionally permissive in legacy mode. Bound mode must verify the copied SDK/client retry controls rather than trusting this helper's best effort.
- `_call_slot`, `prime`, `fan_out`, `ResearchTools._search_uncached/_fetch_uncached`, and linear-engine best-effort/finalize wrappers must propagate the same typed spending exception.
- Search has a raw Firecrawl POST inside a 429 retry loop. Fetch has an async Firecrawl POST followed by optional Jina/Exa/direct fallbacks. Required mode must close both fallback selectors.
- The default linear model factory currently constructs primary and fallback before gateway initialization; it needs preconstruction route/child-contract admission.

## Progress and interface questions

- [x] Confirmed workspace and branch `codex/target-run-spending`; observed shared handoff edits and preserved them.
- [x] Read source and sent exact seams/questions to the core owner before source changes.
- [x] Received and implemented frozen model/tool request shapes, usage callback, async dispatch, environment/module-hash validation and spawn-bound root operation.
- [x] Implemented the owned slice and captured guarded scenario evidence.
- [x] Independent review is clean for the final owned source; gateway SHA-256 is `dd678ec3961cc0f1ab6d2380182403ee3a93ec4bbe428150fe732a25a743b7fa`.
- [x] Reconfirmed all 53 spending scenarios against stable shared-core `8036fc54…` in `/private/tmp/run-spending-child-stable-20261029-01` (identical pre/post hash).
- [x] Built, hashed, and executed the actual installed LangChain/OpenAI adapter proof without model doubles; supplied the portable private dependency package to launcher owner Carver.
- [x] Closed the later loaded-request gap with 61 spending scenarios plus 645 compatibility scenarios passing; narrow independent review is clean.

## Issues, mistakes, recoveries

Intermediate setup errors, review findings, and their corrections are preserved in Updates below. No guard changes, temporary stubs or provider calls were made. The new loaded-request check closes a separately discovered bootstrap-check/producer-reread gap; older transport acceptance does not claim this new check.

## Verification and remaining work

The current loaded-request gate `/private/tmp/run-spending-child-request-scope-20261029-02` passed **706 tests: 61 spending scenarios and 645 compatibility scenarios**. Exit status is 0, shutdown completed, identity was preserved, tracked source drift is empty, and explicit post-run core/linear/test hashes match the verified values below. The guard recorded four admitted hashed performance-fixture children and two baseline subprocess probes, with no recorded network event. Independent narrow review found no actionable bypass or overrestriction. The valid real-run timeout control still reaches one physical model attempt; the new scope guard does not mask that later negative case.

The earlier transport gate `/private/tmp/run-spending-child-final-20261029-02` passed **698 tests: 53 spending scenarios and 645 compatibility scenarios**. Its explicit shared-core pre/post hash changed from `25a79991…` to `8036fc54…`, so it was followed by `/private/tmp/run-spending-child-stable-20261029-01`: all 53 scenarios passed with identical pre/post core `8036fc54…`. These receipts remain historical evidence for the preceding source state.

Production behavior now qualifies the served model and credential before constructing the closed adapter, retains the verified full input ceiling and final output cap, captures raw HTTP usage before SDK/LangChain conversion, denies hidden retries/auth flows/redirects/hooks/tracing, and carries required context through every owned worker pool. Only exact local web-search/web-fetch function schemas are admitted. Every Firecrawl POST retains the entire pinned tool-unit envelope. Local tool cache and singleflight hits do not dispatch or debit. Model alias `glm` selects configuration; its served model `glm-5.3` remains the qualified/billed model.

Validation fidelity is explicit: store, gateway, Firecrawl providers, research tools, linear engine, and OpenAI SDK paths are real. Model responses and HTTP sends are fake. The backend test environment lacks LangChain, so the concrete model and callback carriers are test doubles; installed LangChain source was inspected read-only for the supported API behavior. This is offline implementation evidence, not live billing, deployment, or end-to-end private-launcher acceptance.

The later user-requested **actual installed-adapter proof removes that model-double limitation**. `/private/tmp/run-spending-actual-langchain-20261029-03/actual-adapter-result.json` and `completed.json` prove actual ChatOpenAI construction, static tool binding, invocation, OpenAI SDK JSON serialization, gateway accounting, Firecrawl providers, and one real ledger. Only HTTPX MockTransport is fake. Eight HTTP mock calls correspond to eight distinct retained reservations totaling **66,112 micro-USD**, with eight provider-reported observations and zero additional cache-hit debit. The cases cover JSON repair, output widening from 8 to 16, malformed choices after raw usage capture, Firecrawl search/scrape, and alias `glm` → served `glm-5.3`.

This proof privately staged **37 existing installed distributions / 2,150 files / 29,138,913 bytes**, including langchain-openai 1.2.1, langchain-core 1.3.3, and OpenAI 2.32.0. It installed the repository's unchanged Guard before application imports and executed no `.pth` files. All **1,297 imported dependency file pins** match the staged dependency manifest. Guard exit is 0, shutdown completed, identity is preserved, and source drift is empty. The guard denied two socket-construction capability probes (urllib3 IPv6 detection and LangChain socket-option detection) and two metadata subprocess probes. Source-only attribution is in `probe-origins.jsonl`; these are blocked attempts, not zero attempted activity. No connect/bind/DNS/send was admitted.

Portable package: `/private/tmp/run-spending-langchain-proof-20261029-01/`. `dependencies.json` pins every copied dependency file; `package-pins.json` pins scripts/README/manifest. `proof.run_proof(output_dir, registered_active_binding)` consumes only the supplied allowance; the child MUST NOT call its standalone `fixture_authority` or `main`. `proof.pin_loaded_dependencies(private_site_dir)` exports import pins and adds them to the existing Guard receipt. Launcher owner Carver (`01a185bd-6cb8-7052-81f2-af31bdb5d0af`) received the exact paths and pins for the coordinator's private CPython/registered-child proof. No production chmod, dependency installation, or launcher edit was performed here.

| Verified file | SHA-256 |
|---|---|
| `deerflow_bridge/run_spending.py` (core owner) | `b54cac7c001c5f46106e3593e7a5ad4f66a6711488bd5679fee0f35ec889f9d5` |
| `deerflow_bridge/research_gateway.py` | `dd678ec3961cc0f1ab6d2380182403ee3a93ec4bbe428150fe732a25a743b7fa` |
| `deerflow_bridge/search_tools.py` | `5a21e658d4445be846aea3c99fad6079923e637775fe6be30627620c0add4009` |
| `deerflow_bridge/cached_fetch.py` | `2fa98dcf79fdc6f24cee74b7d7c4c299d6e943a4947ed63e95b8205d1b58b94e` |
| `deerflow_bridge/linear_research.py` | `54c489fbe41e424689fc2722cf2376a8eb0f934c2abdd0bdb611932378bde44c` |
| `backend/tests/test_run_spending_child_transports.py` | `685a48678de1231b5295da1e014a65668409008540d0a947d42d6e4449c4ff65` |
| Private proof `proof.py` | `da6482cd6df0f4109006de59ab99f54883f8419edda5279e16b46ca33a2127d0` |
| Private `dependencies.json` | `36ba5f3487f15ea88e0dee910fb62bc8390d677fa17a39bbac5d8d72cd52297c` |

Coordinator dependencies remain outside ownership: preserve the required binding/module/operation contract in the no-site child bootstrap; prohibit legacy/extract-only salvage and unpriced alternate children; propagate terminal spending failure through the outer child wrapper and parent lifecycle. Do not infer whole-feature completion from this owner slice.

Carver received the reviewed new linear hash `54c489fb…` for private-runtime refresh. The existing actual-adapter proof `-03` explicitly pins earlier core `8036fc54…` and linear `d2880630…`; it is not relabeled as the new loaded-request proof. Package dependency/script hashes remain unchanged. The coordinator's fresh private-process proof must use the new app/source pins.

To reproduce the focused check, use a new canonical `/private/tmp` directory:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/run-spending-child-NEW \
  -q --tb=short backend/tests/test_run_spending_child_transports.py
```

The combined gate additionally selected `test_research_gateway.py`, `test_bridge_search_and_cache.py`, `test_research_engine_v3.py`, `test_research_engine_v3_hardening.py`, `test_three_part_and_fetch_retry.py`, `test_backtest_search_fetch.py`, `test_research_gateway_official_data.py`, and `test_news_research.py`, registering the exact `backend/tests/fixtures/gateway_performance.py` through the existing `--allow-python-script` flag. The guard was never modified.

## Updates

- 2026-10-29: Created after initial source trace, before source edits; recorded owned scope, acceptance scenarios and outstanding shared-interface questions.
- 2026-10-29: Baseline `/private/tmp/run-spending-child-baseline-20261029-01` yielded 485 passing gateway checks and four guard-blocked subprocess tests because the existing `backend/tests/fixtures/gateway_performance.py` was not registered. This is a test invocation error, not spending behavioral evidence. The correction uses the runner's existing exact-script hash registration; no guard changes.
- 2026-10-29: Corrected baseline `/private/tmp/run-spending-child-baseline-20261029-02` passed all 510 checks in `test_research_gateway.py` and `test_bridge_search_and_cache.py`, including the explicitly registered performance fixture. Independent read-only bypass review delegated to Kant (`01a1859c-3a30-7a83-afba-145b804a9d92`). Bound-mode plan additionally closes `_configure_data`, `_configure_context`, and `_collect_prediction_markets` before their optional provider construction/acquisition.
- 2026-10-29: Applied interface-independent context propagation in gateway fan-out, the sync-to-async worker, and linear tool fan-out. Each job receives a distinct copied Context; no core API or temporary stub is assumed. Baseline receipt also records two blocked subprocess probes (`uname` and an unregistered executable), four admitted hashed fixture children, zero recorded network attempts, and preserved identity. The blocked probes are not described as zero attempted activity.
- 2026-10-29: Frozen store contract read at contracts.md section 35 onward. Implemented exact sync/async dispatch request shapes, conservative full Firecrawl envelope reservations, model final-cap/serializer inspection, required-context checks, construction-time qualification, and typed-stop preservation. Six targeted legacy concurrency/async checks passed in `/private/tmp/run-spending-child-context-20261029-01` before core-dependent changes. Independent source review confirmed nested tool context, outer daemon timeout, archive lookup and exception-valued fan-out hazards; all are included in the integration checks. Awaiting exact parent root-operation carrier and account/credential-fingerprint convention; do not infer these authority fields.
- 2026-10-29: Contract clarifications froze credential SHA-256 selection identity (not independent account verification), approved local static function schema, full tool-unit envelopes, and a fourth spawn-bound operation environment key. Adapters now use those exact conventions. First two acceptance attempts (`/private/tmp/run-spending-child-acceptance-20261029-01` and `-02`) exposed fixture setup mistakes: the registry must preexist, and read-only SQLite probes must use canonical `Path.as_uri()`. Fixed only the fixture; no guard/store relaxation. These runs are not behavioral acceptance evidence.
- 2026-10-29: Acceptance `-03` reached 22 passing scenarios and reproduced a core required-environment-removal gap. Franklin corrected it; expanded `-04` passed that case and 30 others, then exposed a WAL/SHM disappearance race during real nested KIQ concurrent calls. Sent the exact `_validate_binding` stack to Franklin rather than editing the shared store. Added actual default-factory, registered-child carrier, raw missing-usage, async-cancellation, disabled finalize-market, and real-engine failure scenarios. Core now binds nested operation hashes to parent ancestry. These are intermediate receipts, not completion claims.
- 2026-10-29: Legacy gate `/private/tmp/run-spending-child-legacy-20261029-01` passed 598 checks across gateway, search/cache, v3 engine, hardening, fetch retries and backtest. Independent review then found five bound-adapter gaps: tracing callbacks, SDK-options vs HTTP-body hashing, LangChain global cache, usage lost before AIMessage conversion, and permissive subclass admission. Repaired all five with a concrete ChatOpenAI identity, cache=False, explicit callback rejection, a per-call model copy and raw SDK resource proxy, exact body hash comparison at raw create, and raw HTTP usage observation before parsing. Outer daemon timeout still halts unknown. Search typed-stop cleanup now releases its legacy singleflight claim. The `-05` run passed its first 26 checks and then exposed test isolation missing the newly added private `_ENV_PIN`; updated the test-only reset in line with the core tests. Added actual OpenAI SDK / fake HTTP checks for plain and GLM final JSON, and malformed choices with usage/over-limit evidence.
- 2026-10-29 03:55 UTC: Final review is clean after closing additional tracing activation, HTTP auth/hook, and admission-before-SDK-reconstruction gaps. Combined gate passed 698 checks; explicit hashing found concurrent shared-core drift, so only the focused spending gate remains to be repeated. Preserved all other owners' changes and made no commits or pushes.
- 2026-10-29: Focused 53-case rerun passed with stable core `8036fc54…`. At the user's request, extended offline evidence to actual installed LangChain and SDK using a private hashed dependency tree, unchanged Guard, and HTTP-only mocks. Final actual-adapter proof `-03` passed with eight exact-body reservations and no source drift; dependency and import pins were supplied to Carver for the separately owned composed launcher/parent proof. Owned source remains unchanged and independently reviewed. No provider, network connection, paid run, scheduler, deployment, primary write, commit, or push was performed.
- 2026-10-29: User approved the narrow loaded-request guard after source review confirmed `deerflow_research.main` reads prompt-file content after launcher validation and passes it unchanged into linear `run`. Added `_validate_spending_request` before bridge import or engine/client construction. It reads only fixed `binding.root/control/request.json` with no-follow directory/file descriptors, regular-file/ownership/write-mode checks and bounded duplicate-key-rejecting JSON, authenticates the full carrier through `validate_bound_request`, then validates the actual loaded question and CLI model/depth/language/authority while preserving immutable target-simulation fields. Output must be the bound pipeline handoff. Updated bound test fixtures to carry the actual seven-field launcher request, preserving the valid control that reaches the intended later transport timeout. Carver retains launcher ownership and receives the new source hash after verification.
- 2026-10-29: Narrow scope gate passed 61 cases; expanded gate passed 706. Kant's read-only review is clean at linear `54c489fb…` and tests `685a4867…`. Verified core is `b54cac7c…`. Sent Carver and the core owner the exact seam, behavior, receipts and source hashes; no launcher, orchestrator, shared-store, completed class/replay, or primary-checkout edits were made by this owner.
