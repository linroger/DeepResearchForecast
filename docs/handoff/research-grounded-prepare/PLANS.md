# Research-grounded forecasting and preparation — implementation plan

## Approval and objective

The user's current instruction explicitly approves implementing the previously presented improvement roadmap and adds a concrete priority: compile deep-research context directly into the Environment setup / personas phase. This plan turns that approved direction into bounded implementation slices. It does not authorize statistical calibration claims, probability promotion from simulation, or unattended paid experiments.

The primary vertical slice is RESEARCH → bound research generation → PREPARE → per-actor persona / shared environment / quantitative world guidance → real decision and world-update consumers. Existing actor-intelligence/context/role, official-data and world-spec contracts remain authoritative. New projections must not become an alternate source authority.

## Source and preservation

Use the isolated managed worktree on `codex/research-grounded-prepare`, based on committed `6ab52f77`. The primary checkout has concurrent Mandarin, forecast-task/calendar and arbiter work, plus staged news changes. Treat those as independently owned; preserve them, and validate a composed candidate before active-source delivery. No saved run may silently acquire a new research generation or policy during reuse.

## Invariants

1. Observations, preliminary data, estimates, projections, actor-stated plans, analytical inferences and modeling assumptions stay distinct. Targets and forecasts never become initial observed state.
2. Every quantitative anchor retains source/series identity, entity/metric, native value and units, date/period/status and input generation. Historical ranges are diagnostic context, not hard causal bounds.
3. Actor-specific projections obey existing `actor_knows`/visibility denial precedence. Shared environment text contains only public/admitted information. The modeler/arbiter can receive a separately labelled broader research projection without granting that knowledge to actors.
4. Only explicit, validated mechanisms/constraints may enforce resources, permissions, deadlines or material effects. No causal elasticity, budget, probability or authority is invented because a field is missing.
5. Sealed preparation binds all compiled artifacts and actual runtime projections. Current-version tamper/missing/stale proof fails closed; old unversioned saved configurations retain their explicit compatibility path.
6. Simulation remains diagnostic-only by default; research-derived context may guide simulation but simulation outputs do not become evidence or probability inputs.
7. Research revisions are evidence-driven and versioned before writing. Experiments have stable proposition IDs, full denominators and cost accounting; enabling an experiment is distinct from promoting its result.

## Ordered slices

### A. Bound research preparation compiler (first complete vertical slice)

Compile a versioned, deterministic preparation projection from the exact consumed research dossier, official-data carrier and selected actor packs. Produce public environment guidance, actor-specific qualitative/quantitative context, modeler-only uncertainty/assumption guidance, evidence gaps and provenance. Reuse existing contracts rather than create a second actor registry. Persist the projection plus a manifest; add it to configuration sealing/reuse and public artifact discovery where appropriate.

### B. Real quantitative and qualitative consumers

Wire the projection into profile/role generation, shared environment setup, default OASIS decision briefs and world updates, and the native world compiler/modeler. Preserve source identities and measurement semantics in world seeds instead of dropping them after selecting the latest value. Use budgeted, relevance-selected complete facts with omission receipts. Validate actual prompt bytes and state transitions, not merely artifact presence.

### C. Pivotal research quality and assessment

Strengthen typed claim support/identity/date/modality handling and source-origin metadata at the research handoff. Keep support status separate from numerical occurrence. Add an explicit bounded post-gather assessment path with versioned initial/final scenario frames and source-linked revision reasons. Convert conviction/spread quotas into diagnostics while retaining resolvability, factual and probability-consistency gates. Preserve saved policy behavior and record failed/insufficient-evidence stopping reasons honestly.

### D. Causal mechanics and replay

Close concrete default-engine affordability/menu-coverage and commitment-deadline gaps; make runtime guidance actionable without fabricating quantitative effects. Persist replay-complete accepted arbiter inputs/settings. Extend existing native observation/belief contracts where needed for typed proposition provenance and supersession, using intervention tests and existing kernel authority.

### E. Controlled adaptive/discovery experiments

Provide bounded, explicitly versioned experimental paths for branch-local actor responses and simulation-derived investigation questions. Branches must retain their own observations/state and declared uncertainty source; a query suggestion cannot be admitted as an external fact. Keep paid execution opt-in and cap work. Prefer completing and validating each narrow capability over broad unmeasured default promotion.

### F. Evaluation and delivery

Extend existing evaluation tooling with pre-outcome enrollment, stable question/event-family identity, explicit unresolved/failed dispositions and appropriate same-evidence / equal-cost contrasts. Do not treat current diagnostic-only invariance as probability lift. Reuse the resolution registry and scorers. Finish bilingual documentation, feature/progress/handoff records, independent review, scoped commits/push and safe active-checkout reconciliation.

## Acceptance matrix

| Boundary | Positive scenario | Negative / contrast |
|---|---|---|
| Research → preparation | Bound official observations and sourced actor goals reach the compiled projection with correct identities | Wrong entity/unit/date, target-as-actual, missing source, conflicting values, or changed generation remains a typed gap or is rejected |
| Preparation → personas | Distinct actors receive relevant goals, constraints, plans, relationships and permitted quantitative context in actual platform role bytes | Hidden/denied/foreign-actor facts never enter shared or other-actor prompts; tight budgets retain identity and disclose omissions |
| Preparation → world | Historical observations seed the correct variables; assumptions/forecasts are labelled guidance; actual decision/arbiter inputs contain the intended context | Mere announcements do not become completed capacity; observational correlation does not become a causal coefficient |
| Persistence / reuse | Same admitted inputs reproduce/reuse the same projection; validated consumers load it after restart | Tampered/missing/current-version proofs, changed research, stale source selection and partial writes fail safely without modifying old owner artifacts |
| Research assessment | Decisive supported evidence can change a post-gather assessment, with a recorded version and reason | Duplicate evidence is not independent corroboration; changed scenario definitions are not disguised as a probability-only update; justified ambiguity passes |
| Mechanics / branches | Affordable actions, operative deadlines and branch-local information produce controlled consequences | No over-budget execution, menu starvation, premature breach, cross-branch knowledge or private-belief-to-world shortcut |
| Evaluation | Every enrolled case joins to a published prediction and admitted outcome or explicit disposition | Pending/failed/void cases cannot disappear or be scored as No; correlated revisions do not inflate sample size |
| Report separation | Research-guided simulation changes only its diagnostics and deterministic report bridge | Same evidence plus changed simulation still yields identical effective forecast requests under supported production policy |

## Verification method and stopping condition

Use the existing `backend/scripts/main_offline_pytest.py` with the provisioned interpreter, guards before imports, fresh private evidence directories, named child fixtures only, source hashes and independent producer/consumer reviews. Use real service/compiler/kernel/API methods with scripted provider boundaries. Run relevant frontend consumers/build for changed surfaces. Existing live saved inputs stay untouched; replay copies may be used. New code is complete only when every implemented slice's actual-consumer scenarios and failure controls pass. Prospective predictive skill requires future outcomes and remains a separately reported evidence limit.
