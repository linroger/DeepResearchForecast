"""Stage-specific execution over durable units; no publication or route policy."""
from __future__ import annotations

from contextlib import nullcontext
import json
import math

from .contracts import ScopedImport, TranslationError, canonical, safe_error, scope_digest
from .store import file_lock

# 6,500 is a batching target, not a bypassable request ceiling. The hard bound
# includes the system prompt, serialized metadata and previous repair candidate.
BATCH_TARGET_TOKENS = 6500
MAX_INPUT_TOKENS = 16000


def _estimate(text):
    return math.ceil(sum(2 if ord(char) > 127 else .3 for char in text))


def _batch(units, stage, context):
    keys, tokens, repair = [], _estimate(context), None
    for key, unit in units.items():
        if unit['stage'] != stage:
            continue
        is_repair = bool(unit['repair_count'])
        if stage == 'pending' and repair is not None and is_repair != repair:
            continue
        size = _estimate(unit['source'])
        if stage == 'review' or is_repair:
            size += _estimate(unit['candidate'] or '')
        if is_repair:
            size += _estimate(canonical([unit['issues'], unit.get('feedback')]))
        if keys and (len(keys) >= 18 or tokens + size > BATCH_TARGET_TOKENS):
            break
        repair = is_repair
        keys.append(key)
        tokens += size
    return keys


def _envelope(value, field):
    if not isinstance(value, dict) or not isinstance(value.get(field), dict):
        raise TranslationError('invalid_envelope', f'Model response requires a {field} object.', retryable=True)
    return value[field]


def _protocol_failure(unit, error, phase):
    count = unit['protocol_failures'].get(phase, 0) + 1
    unit['protocol_failures'][phase] = count
    unit['error'] = error
    unit['issues'] = [f"{error['message']} ({error['code']}; {phase})"]
    if count >= 2 or not error['retryable']:
        unit['resume_stage'] = unit['stage']
        unit['stage'] = 'failed'


def execute(store, job_id, fence, llm, *, seed=None, on_progress=None):
    from .. import model_translation as model
    from .scheduler import assert_current_task_active, update_progress

    job = store.job(job_id)
    lang, context, initial_calls = job['lang'], job['context'], job['calls']
    identity = json.loads(job['identity'])
    resource = identity.get('resource') or None
    binding = scope_digest(resource)
    references = identity.get('references') or {}
    units = store.units(job_id)
    reused = 0

    def receipt_valid(source, candidate, receipt):
        return model.valid_receipt(source, candidate, lang, receipt, context=context,
                                   reference_context=references)

    for key, unit in units.items():
        if model._immutable_carrier(unit['source']):
            receipt = model._receipt(unit['source'], unit['source'], lang, context, None, llm, references)
            receipt.update(preserved=True, resource_scope_sha256=binding,
                           reviewer_model='not-required-immutable-carrier')
            unit.update(stage='accepted', candidate=unit['source'], receipt=receipt, issues=[], error=None)
            continue
        if len(unit['source']) > model._MAX_ENTRY:
            unit.update(stage='failed', issues=['entry exceeds bounded whole-block limit'],
                        error={'code': 'entry_too_large', 'message': 'Entry exceeds bounded whole-block limit.',
                               'stage': 'inventory', 'retryable': False})
            continue
        if unit['stage'] == 'accepted':
            if (receipt_valid(unit['source'], unit['candidate'], unit['receipt'])
                    and (unit['receipt'] or {}).get('resource_scope_sha256') == binding):
                reused += 1
                continue
            unit.update(stage='pending', candidate=None, receipt=None, repair_count=0, protocol_failures={})
        previous = (seed or {}).get(key)
        receipt = previous.get('receipt') if isinstance(previous, dict) else None
        old_binding = receipt.get('resource_scope_sha256') if isinstance(receipt, dict) else None
        scope_ok = (old_binding == binding or (old_binding is None and isinstance(seed, ScopedImport)
                                              and seed.binding == binding))
        if (scope_ok and isinstance(previous, dict) and previous.get('source') == unit['source']
                and receipt_valid(unit['source'], previous.get('target'), receipt)):
            imported = dict(receipt)
            if binding is not None and old_binding is None:
                imported.update(resource_scope_sha256=binding, import_provenance='validated-legacy-reader')
            unit.update(stage='accepted', candidate=previous['target'], receipt=imported, issues=[], error=None)
            reused += 1
        elif unit['stage'] == 'failed' and (unit.get('error') or {}).get('code') != 'entry_too_large':
            unit['stage'] = unit.pop('resume_stage', 'pending')
            unit['protocol_failures'] = {}
            if unit['stage'] == 'pending':
                unit['repair_count'] = 0
    store.checkpoint(job_id, fence, units)

    def result():
        value = model.VerifiedTranslations(calls_used=store.job(job_id)['calls'] - initial_calls)
        for key, unit in units.items():
            if unit['stage'] == 'accepted':
                value[key], value.receipts[key] = unit['candidate'], unit['receipt']
            else:
                value.issues[key] = unit['issues'] or ['translation call budget exhausted']
                if unit.get('diagnostic'):
                    value.diagnostics[key] = unit['diagnostic']
        value.job = store.summary(job_id)
        value.job['coverage']['reused'] = reused
        return value

    def progress():
        update_progress(result().job)
        if on_progress is not None:
            try:
                on_progress(result())
            except Exception:
                pass

    def repair(unit, issues):
        unit['issues'] = issues
        if unit['repair_count']:
            unit.update(stage='failed', resume_stage='pending')
        else:
            unit.update(stage='pending', repair_count=1)
            unit['protocol_failures'] = {}

    def consume_saved_results():
        changed = {}
        for key, unit in units.items():
            if unit['stage'] == 'validate':
                issues = model.structure_issues(unit['source'], unit['candidate'], references)
                if issues:
                    feedback = model._structure_feedback(unit['source'], unit['candidate'], references)
                    unit['feedback'] = feedback
                    unit['diagnostic'] = model._failure_diagnostic(unit['source'], unit['candidate'], feedback, unit['repair_count'] + 1)
                    unit['error'] = {'code': 'structure_rejected', 'message': issues[0], 'stage': 'validating', 'retryable': True}
                    repair(unit, issues)
                else:
                    unit.update(stage='review', issues=[], error=None)
                changed[key] = unit
            elif unit['stage'] == 'review_returned':
                verdict = unit.pop('pending_verdict')
                unit['stage'] = 'review'
                if (not isinstance(verdict, dict) or any(type(verdict.get(k)) is not bool for k in
                        ('faithful', 'complete', 'target_language')) or not isinstance(verdict.get('issues'), list)):
                    _protocol_failure(unit, {'code': 'invalid_verdict', 'message': 'Reviewer omitted required boolean verdicts or issues.',
                                             'retryable': True, 'stage': 'reviewing'}, 'review')
                elif model._verdict_ok(verdict):
                    receipt = model._receipt(unit['source'], unit['candidate'], lang, context, verdict, llm, references)
                    receipt['resource_scope_sha256'] = binding
                    unit.update(stage='accepted', receipt=receipt, issues=[], error=None, diagnostic=None)
                else:
                    issues = ['semantic review rejected translation', *[str(item)[:300] for item in verdict['issues'][:8]]]
                    unit['error'] = {'code': 'semantic_rejected', 'message': issues[0], 'stage': 'reviewing', 'retryable': True}
                    repair(unit, issues)
                changed[key] = unit
        if changed:
            store.checkpoint(job_id, fence, changed)
            progress()

    provider_failed = False
    while True:
        assert_current_task_active()
        consume_saved_results()
        phase = 'review' if any(u['stage'] == 'review' for u in units.values()) else 'pending'
        keys = _batch(units, phase, context)
        if not keys:
            break
        remaining = job['max_calls'] - store.job(job_id)['calls']
        if remaining < (1 if phase == 'review' else 2):
            break

        def request(selected, phase=phase):
            if phase == 'review':
                payload = {'target_language': lang, 'context': context, 'pairs': {
                    key: {'source': units[key]['source'], 'translation': units[key]['candidate']} for key in selected}}
                system, field, stage = model._REVIEW, 'reviews', 'reviewing'
            else:
                payload = {'target_language': lang, 'context': context,
                           'entries': {key: units[key]['source'] for key in selected}}
                if any(units[key]['repair_count'] for key in selected):
                    payload.update(repair=True, previous={key: units[key]['candidate'] for key in selected},
                                   issues={key: units[key]['issues'] for key in selected},
                                   structure_feedback={key: units[key]['feedback'] for key in selected if units[key].get('feedback')})
                system, field, stage = model._TRANSLATE, 'translations', 'translating'
            if references:
                payload['document_references'] = references
            if any(units[key]['protocol_failures'] for key in selected):
                payload['response_requirements'] = {'required_keys': selected, 'format': field,
                    'note': 'Return every requested key exactly once with the required fields.'}
            return system, payload, field, stage

        system, payload, field, stage = request(keys)
        while len(keys) > 1 and _estimate(system) + _estimate(canonical(payload)) > MAX_INPUT_TOKENS:
            keys.pop()
            system, payload, field, stage = request(keys)
        if _estimate(system) + _estimate(canonical(payload)) > MAX_INPUT_TOKENS:
            error = {'code': 'request_too_large', 'message': 'This entry and its context exceed the translation input budget.',
                     'stage': stage, 'retryable': False}
            for key in keys:
                _protocol_failure(units[key], error, phase)
            store.checkpoint(job_id, fence, {key: units[key] for key in keys})
            progress()
            continue
        attempt = store.reserve(job_id, fence, stage, keys)
        try:
            gate = file_lock(str(store.path) + '.provider.lock') if store.path != ':memory:' else nullcontext()
            with gate:
                response = _envelope(model._chat(llm, system, payload), field)
            assert_current_task_active()
        except Exception as exc:
            error = safe_error(exc, stage)
            store.finish_attempt(job_id, fence, attempt, error)
            for key in keys:
                _protocol_failure(units[key], error, phase)
            store.checkpoint(job_id, fence, {key: units[key] for key in keys}, phase=stage)
            progress()
            if not error['retryable']:
                provider_failed = True
                break
            continue
        # One transaction saves the entire returned batch and its outcome before
        # any per-entry parsing. The same rule protects returned review verdicts.
        for key in keys:
            unit = units[key]
            if key not in response:
                _protocol_failure(unit, {'code': 'missing_entry', 'message': 'Model omitted a requested entry.',
                                         'retryable': True, 'stage': stage}, phase)
            elif phase == 'pending':
                candidate = response[key]
                if not isinstance(candidate, str) or not candidate.strip():
                    _protocol_failure(unit, {'code': 'invalid_candidate', 'message': 'Model returned an empty or non-text translation.',
                                             'retryable': True, 'stage': stage}, phase)
                else:
                    unit.update(candidate=candidate, stage='validate')
            else:
                unit.update(pending_verdict=response[key], stage='review_returned')
        store.checkpoint(job_id, fence, {key: units[key] for key in keys}, phase=stage, returned_attempt=attempt)
        progress()

    for unit in units.values():
        if unit['stage'] not in {'accepted', 'failed'}:
            unit['issues'] = unit['issues'] or (['translation stopped after provider failure'] if provider_failed else ['translation call budget exhausted'])
    complete = all(unit['stage'] == 'accepted' for unit in units.values())
    store.checkpoint(job_id, fence, units, state='completed' if complete else 'failed', phase='completed' if complete else 'incomplete')
    progress()
    return result()
