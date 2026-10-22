# Simulation After-Action Record fixtures (`simulation-record/v1`, ADR 0003)

Records as `GET /api/simulation/<id>/record` serves them once the deterministic gate passed
(design §3.2); shape per `backend/app/services/simulation_record_contract.py`, field semantics
per `docs/handoff/simulation-after-action-record/design.md` §4. Used by
`simulationRecordView.test.mjs` (T12).

| File | Source |
|---|---|
| `simulation_record.en.json` | Compiled 2026-10-23 from the local reflexive-OASIS run `backend/uploads/simulations/sim_3ec25e64209e` (9 committed daily rounds, 2026-10-23 → 2026-10-31), trimmed to its first three rounds (`rounds_planned` and `rounds_committed` set to 3 so the contract's one-period-per-committed-round rule holds). Periods come from `world_state_history.jsonl` (arbiter narrative verbatim, `diff.variables_changed` with the cause read from `world_state.json` variable histories, `diff.interactions_changed` as offers, world events of the round), moves from `world_actions.jsonl` through the contract's `ACTION_PUBLIC_FIELDS` allowlist only — `private_rationale` was never read, and the builder asserts no such text appears. Shares are the round-3 row of the history; `paths.k` is 1 because the run wrote no `world_paths.json`. The banner is byte-equal to `sim_provenance.SIM_BANNER_EN`. |
| `simulation_record.zh.json` | The same record with `language: zh`, the `SIM_BANNER_ZH` banner and short Chinese arbiter narratives / synthesis in place of the English ones (actor statements stay in the run's language). Exercises the Chinese interface, not a Chinese run. |
| `simulation_record.hollow.json` | Hand-written health stub for a hollow run (design §3.1 "Health stub", invariant I-16): zero committed rounds, no periods, no narrative. |
| `simulation_record.paths.json` | Hand-written two-period record with synthetic actors ("Actor A/B/C") covering what the real run lacks: a K=4 path spread (p10–p90), a converged share trajectory, a crossed red line, a fired shock, an alliance shift, an arbiter-failed (mechanical-only) round, a bounded LLM synthesis and non-zero track records. |
