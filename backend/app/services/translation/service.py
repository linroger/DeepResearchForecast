"""One durable executor entrypoint for document and structured adapters."""
from contextlib import nullcontext
import uuid

from .contracts import digest
from .store import Store, database_path, file_lock


def translate_entries(llm, pairs, target_lang, *, context="", max_calls=48,
                      on_progress=None, identity=None, seed=None, force=False, reference_context=None):
    from ..model_translation import ENGINE
    from .engine import execute
    if target_lang not in {"en", "zh"}:
        raise ValueError("unsupported translation language")
    if any(not isinstance(key, str) or not key or not isinstance(text, str) or not text.strip() for key, text in pairs):
        raise ValueError("translation entries must have nonempty string keys and text")
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("duplicate translation entry keys")
    persistent = identity is not None
    if persistent and (not isinstance(identity, dict) or not identity.get("kind") or not identity.get("ref_id")):
        raise ValueError("durable translation identity requires kind and ref_id")
    bound = {"resource": identity or {}, "engine": ENGINE, "policy": "staged-review/v2"}
    if reference_context:
        bound["references"] = reference_context
    if force:
        from .scheduler import current_task_id
        bound["refresh"] = current_task_id() or uuid.uuid4().hex
        seed = None  # Explicit refresh regenerates; ordinary retry alone imports receipts.
    path = database_path() if persistent else ":memory:"
    with Store(path) as store:
        job_id = store.create_job(bound, pairs, target_lang, context, max(0, int(max_calls)))
        lock = file_lock(path.parent / "locks" / (digest(job_id) + ".lock")) if persistent else nullcontext()
        with lock:
            fence = store.claim(job_id, additional_budget=max_calls)
            return execute(store, job_id, fence, llm, seed=seed, on_progress=on_progress)


def invalidate_assembly(job_id, issues):
    """Do not cache an accepted unit set that fails the whole-document gate."""
    path = database_path()
    with file_lock(path.parent / "locks" / (digest(job_id) + ".lock")):
        with Store(path) as store:
            fence = store.claim(job_id)
            units = store.units(job_id)
            for unit in units.values():
                unit.update(stage="failed", resume_stage="pending", receipt=None, issues=list(issues),
                            error={"code": "assembly_rejected", "message": "Assembled document changed its structure; retry pending repair.",
                                   "stage": "assembling", "retryable": True})
            store.checkpoint(job_id, fence, units, state="failed", phase="assembling")
