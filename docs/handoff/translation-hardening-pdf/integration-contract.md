# Approved translation v2 integration contract

User approved full redesign on2026-10-26. Parent owns backend/app/services/translation/{contracts,store,engine,service,scheduler}.py, model_translation.py, generic jobs API and app registration. Other workers MUST NOT edit these files. Existing dirty bytes are the accepted starting point; do not revert them.

## Shared entry/document APIs (parent provides)

Existing model_translation.translate_entries gains keyword-only `identity=None, seed=None, force=False`; existing translate_document gains `identity=None, previous_proof=None, force=False`. All existing arguments and return shapes remain. Default identity=None runs isolated in-memory for pure helper/backward compatibility; actual app adapters MUST pass identity for durable execution. Identity is a JSON object containing `kind`, `ref_id`, `scope` (visibility/selection context), and any canonical source fingerprint. The service adds target_lang, engine/context hashes and exact ordered source entries. Never put credentials in identity. Results retain receipts/calls_used/issues/diagnostics and gain `job` summary. Document proof retains existing section format and gains `job`.

`seed` is mapping key -> {source,target,receipt}; each receipt is revalidated. previous_proof is a prior document's model_translation proof, even if incomplete: only individual matching source/target/context/language receipts import. force=False reuses accepted units and saved candidates; force=True creates a replacement attempt retaining accepted publication externally. Ordinary retry is NOT force. Markdown/current engine receipt validation stays compatible; orchestration has its own v2 schema.

## Durable operation scheduler (parent provides)

`from app.services.translation.scheduler import register_handler, submit, status, retry, start_scheduler`
- `register_handler(kind, handler)`: handler(payload: dict) -> JSON-safe dict; register from the owning module, not an anonymous lambda. Handler performs existing domain audit/publication using shared translate_* APIs.
- `submit(kind, identity: dict, payload: dict, *, force=False) -> dict`: idempotently create/attach operation and signal elected scheduler. Payload contains stable resource identifiers, expected source hashes and explicit requested mode. Returns unified task summary with `job_id`, `job_state`, `phase`, `status`, `result`, `issues`, counters/actions where known. If completed and force=False, reuse matching task; retry of interrupted/failed is explicit.
- `status(job_id) -> dict | None`: read only, no provider work. Every route still checks requested resource authority/identity.
- `retry(job_id) -> dict`: requeues only interrupted/failed/cancelled task under same identity. Existing call budget/candidate receipts survive.
- `start_scheduler()`: explicit Flask lifecycle starts one local coordinator; does not auto-retry interrupted work. submit also ensures scheduler is started for CLI/test consumers. Existing handlers register before dispatch.

New generic `/api/translations/jobs/<job_id>` GET and `/retry` POST expose same summary; resource facades retain current public payloads and attach `translation_job` where possible. Backend domain worker owns replacement of its route-level independent threads with submit/status; do not keep a second writer path. Never drop existing body vs structured completeness distinction.

## Frontend contract

One shared useTranslationJob/observer implementation supports resource transport adapters for existing routes. It owns request identity/revisions, polling/backoff/reconnection/unmount. Controls keep source vs target display selection. Use attached translation_job when present; normalize legacy compatibility states only in transport adapters. Review-only retry must not request force. UI/PDF language means admitted displayed language; explicit target label. All translation surfaces and completed SimulationRecord inherit same workflow. Never submit private hidden text.

## Publication/PDF ownership

Report adapter worker owns report_agent.py, backend/api/report.py, backend/api/research.py and new translation/artifacts.py (parent must not edit these). Implement immutable-generation/manifest resolver and adapt report/dossier reader/publication/export under existing locks. All new outputs bind exact source and language; preserve existing accepted sidecars. Research PDF must consume verified bytes, never reread mutable path; source/publication drift returns409. Use unique temporary render paths, atomic cache publication and guarded real PDF tests. Work with parent for cross-package needs; keep documented signatures stable.

## Write ownership

Parent: shared core/scheduler/generic API/app registration and integration evidence.
Report worker: report_agent.py, report.py, research.py, translation/artifacts.py, report/dossier/PDF tests.
Overlay worker: artifact_translation.py, translation_tools.py, graph.py, simulation.py, overlay backend tests.
Frontend worker: frontend/src and frontend/tests only.
Each worker records changed paths and verification in its own docs/handoff/translation-hardening-pdf/worker-<scope>.md. No commits, service restarts, provider calls or saved-data mutations by workers. Parent coordinates final gate, activation, recovery and delivery.

## Implementation refinements

Scheduler also provides `publication_guard()` for the final activation critical section, `assert_current_task_active()`, and `cancel(job_id)`. Cancellation and publication share a short per-task lock. Generic jobs GET deliberately omits result/identity: translated private data remains with resource-scoped readers. New explicit executor invocation after failure/interruption grants at most max_calls additional calls, preserving the total attempt ledger; a completed replay gets no additional allowance and calls no provider. Report/research/artifact modules all expose register_translation_handler(), registered by create_app before starting the elected coordinator.
