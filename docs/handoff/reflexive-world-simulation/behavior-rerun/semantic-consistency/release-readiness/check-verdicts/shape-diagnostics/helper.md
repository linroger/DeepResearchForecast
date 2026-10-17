# Pure revision-shape helpers

**Status:** Frozen helper bytes verified against the coordinator's green guarded diagnostic gate. Owner verification is recorded below; separate exact-source independent review remains required before a bounded live diagnostic. No behavior/default acceptance is claimed.
**Started (UTC):** 2026-10-17T16:31:36Z

Owned changes are append-only additions to `backend/app/services/world_simulation/review.py`, new `backend/tests/test_world_review_shape.py`, and this note. Existing review, assessment and candidate-repair code must remain byte-identical. No runtime imports, tests, providers, commits or delegation are authorized for this worker.

The shared signatures are `build_revision_shape(raw) -> dict` and `validate_revision_shape(value) -> dict`. Both return detached receipts. Invalid receipt/schema inputs raise `WorldError` with code `invalid_review_shape`; error text never includes input names or values. The builder inspects only root/decision/assessment/checks and the first four check items, using the literal schema-key allowlist and capped counts. The validator enforces the closed eight-node contract, missing-versus-null relationships, parent type/presence, array lengths and nonboolean counters. Neither function changes response acceptance or admits a decision.

The original `review.py` prefix is 9,118 bytes / 163 lines with SHA-256 `ca5bfa35cf3ba8556aa7e8b9a932aebe60095f659d0565689e46ad78ca162846`. Final static verification will compare that exact prefix, parse/compile the owned Python sources without execution, and run static lint only. Approximately twelve meaningful test functions will be authored for the coordinator's guarded runner. Runtime/behavioral acceptance remains coordinator-owned.

## Final interface and behavior

- `build_revision_shape(raw)` is appended at `review.py:192`. It accepts parsed JSON builtins and returns a validated detached `actor-revision-shape/v1` receipt. Unsupported Python values at an inspected location fail with typed `invalid_review_shape`, without representing the value. Unknown-field values, known-field contents such as rationale/verdict, nested structures and array items after check3 are never traversed or copied. Optional diagnostic callers remain responsible for preserving the original known-metered error if building fails.
- `validate_revision_shape(value)` is appended at `review.py:237`. It returns newly allocated bounded nodes/lists after verifying exact fields, eight fixed node names, type tags, sorted unique recognized keys, exact required-key differences, nonboolean capped counts, overflow implications and all parent/child/count relations. Root may be null but cannot be missing; a present null child cannot stand for an absent key, and a missing child cannot stand for a present key. A nonarray checks node requires null checksItemCount and all four item nodes missing.
- Recognition checks the 19 literal allowed keys at each object using membership and its length. It never iterates the raw unknown keys. There are exactly eight node descriptors and at most four check-element reads, independent of input width or nesting depth. No identifiers, field values, arbitrary names, hashes or raw output are recorded. There is no application I/O, logging, model call, dispatch, admission, retry or scoring operation in either helper.
- Existing mode, assessment, candidate-repair and error-context functions were not changed. The original 9,118-byte prefix was rehashed after the append and matched exactly. The helpers are additional diagnostic APIs, not an output-acceptance change.

## Authored checks and verification boundary

The new test file has exactly 12 test functions with bounded parameters. It covers the exact eight-node schema, JSON type taxonomy including boolean versus number, absence versus null, global recognized-key behavior and unknown-key caps, invariance under arbitrary names/values, cyclic/deep values and ignored check tails, capped array lengths, detached receipts, closed-schema/type/sorting rejection, parent-presence contradictions, item-count/nonobject/overflow contradictions, and sanitized typed failures for unsupported fixed-location inputs. The deep-input test uses opaque values and cycles to catch accidental serialization, copying or traversal without generating a large suite.

Static checks passed for both files: `ast.parse`, compilation of the AST to an in-memory code object without execution, and `ruff check --no-cache --select F,E9`. AST inspection confirmed the exact one-positional-argument signatures and the absence of runtime/provider calls in the appended functions. No pytest collection or test execution occurred; these are authored checks, not observed passes. No application/test modules were imported by the verification commands.

| Frozen file | SHA-256 | Static checkpoint |
|---|---|---|
| `backend/app/services/world_simulation/review.py` | `3d2eab97b4020ab6c5f66dca8d5bf3fc0dd85c74655877a1c07f5ace27bc22ad` | 15,007 bytes; 286 lines; original 9,118-byte prefix unchanged; AST/compile and Ruff F/E9 passed |
| `backend/tests/test_world_review_shape.py` | `941ef6e029071fd2263c475f822a9df4c6f9ab8c2f680ff8eede795c1a57a866` | 10,346 bytes; 240 lines; 12 test functions; AST/compile and Ruff F/E9 passed |

Source and test edits are frozen at these hashes. Curie and Poincare can consume the two signatures above; policy-origin binding, error/usage preservation, durable journal bindings and their guarded/runtime verification remain their respective scopes and the coordinator's responsibility. No provider calls, commits, delegation or changes to unowned files occurred. Full behavior/default promotion is outside this diagnostic helper slice.

## Guarded receipt verification — 2026-10-18 Asia/Singapore

The coordinator supplied `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-diagnostics-first-20261017T163814Z-hji9d75i/evidence`. This worker read that existing receipt and its sibling source manifest/verification summary; no test, runtime import or provider request was launched here. This is a note-only update.

The console records **453 passed in 13.89s**. JUnit records 453 cases, zero failures/errors/skips and suite time 13.884 seconds. The verification summary records exitCode 0, `sourceDrift=[]` and 548 source files, matching the manifest entry count. The run includes 34 parameterized pure-helper cases, 12 policy-shape cases and 11 evaluator-shape cases; the remaining cases cover existing consistency/evaluation, withheld diagnostics, strict policy, v3 policy and candidate-repair behavior. These are parts of the same 453-case run, not additive run totals.

For both owned Python files, current bytes equal the copied frozen source and the manifest hashes in the table above. The original 9,118-byte `review.py` prefix still hashes to `ca5bfa35cf3ba8556aa7e8b9a932aebe60095f659d0565689e46ad78ca162846`, confirming that the existing review/assessment/candidate code remains byte-identical to this slice's starting point.

The completed guard receipt records shutdown complete, identity preserved, three storage/logger redirects and two blocked subprocess events. It contains no network event category. This is CPython audit-hook evidence, not an OS sandbox assertion or a claim that no subprocess probes were attempted.

There are no remaining helper-owner findings from this bounded source/receipt check. Because this worker authored the helpers, this note is **not independent review closure**. The coordinator's separate reviewer must close findings on the exact current diagnostic sources before any bounded live diagnostic. The new directed/full36 manifests do not themselves authorize calls; full36 is not authorized by this note. No prompt, acceptance, retry, repair, scoring or spending-policy change is proposed here, and no model-behavior success or default promotion is inferred. Source and tests remain frozen pending the coordinator's next explicit instruction.
