"""Preregistered M5 behavior harness. No default policy, provider discovery or CLI.

The supplied factory is a trusted dependency and must construct a policy without
dispatching. Scripted checks prove mechanics, not model realism. Production
observations call the pure mask helper before hashing; service admission forbids
this evaluation-only field. Cases and rubric are sealed before any factory call.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, ROUND_FLOOR
import fcntl
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .contracts import (
    WorldError, canonical_json, clone, decimal, digest, initial_snapshot,
    quantity, require, validate_snapshot, validate_spec,
)
from .controller import run_to_horizon, slot_id
from .examples import example_spec
from .store import WorldStore

VERSION = 'm5-behavior/v1'
MASK_SCHEMA = 'world-evaluation-mask/v1'
DOMAINS = ('investment', 'trade', 'coalition')
ARMS = ('reflexive', 'external-feedback-ablation')
RUBRIC = {
    'goalConsistency': {
        '0': 'Neither focal comparison decision matches its declared objective and visible record.',
        '1': 'One focal comparison decision matches.',
        '2': 'Both focal comparison decisions match; this is a narrow behavioral proxy.',
    },
    'feasibility': {
        '0': 'More than 20% of committed intents are rejected, or evidence integrity fails.',
        '1': 'At least one but at most 20% of committed intents is rejected.',
        '2': 'All committed intents are accepted; explicit waits are feasible.',
    },
    'consequenceResponse': {
        '0': 'Required physical stimulus absent, or focal post-stimulus decision mismatches visible evidence.',
        '1': 'Physical stimulus and appropriate post-decision exist, but the pre-decision mismatches.',
        '2': 'Physical stimulus and both evidence-appropriate decisions exist. Paired contrast is separate.',
    },
    'explanationRecord': {
        '0': 'Independent qualitative review finds material explanation/record disagreement or absent explanations.',
        '1': 'Independent qualitative review finds partial, ambiguous or incomplete record agreement.',
        '2': 'Independent qualitative review verifies comparison rationales against linked observations and decisions.',
    },
}


def _case_pair(domain, variant, seed):
    pair_id = f'm5-{domain}-v{variant}-s{seed}'
    # Matched arms deliberately share world IDs. Arm identity lives outside the
    # actor payload, so opaque interaction IDs cannot identify the intervention.
    spec = example_spec(domain, simulation_id=pair_id, generation_id=pair_id, seed=seed)
    spec['limits'].update(maxActors=4, maxOutputTokens=4096)
    spec['assumptions'].append({
        'assumptionId': VERSION, 'visibility': {'kind': 'public'},
        'description': 'Synthetic held-out parameter variant; all values, goals and mechanisms are assumptions. '
                       'Seeds label matched repetitions and do not guarantee independent model samples.',
    })
    catalog = {item['templateId']: item for item in spec['actionCatalog']}
    actors = {actor['actorId']: actor for actor in spec['actors']}
    state = spec['initialState']
    if domain == 'investment':
        initial, delta = variant + 2, variant + 1
        state['metrics']['capacity']['value'] = str(initial)
        state['metrics']['input_limit']['value'] = str(initial + delta)
        state['accounts']['producer_stock']['balance'] = '10'
        state['accounts']['raw_supply']['visibility'] = {'kind': 'analyst'}
        spec['flows'][0]['visibility'] = {'kind': 'actors', 'actorIds': ['producer']}
        catalog['expand']['parameters'].update(delta=str(delta), cost=str(variant + 4))
        catalog['expand']['description'] = (
            f'Spend {variant + 4} currency to add {delta} capacity after two days, subject to permit.')
        catalog['expand']['visibility'] = {'kind': 'actors', 'actorIds': ['producer']}
        actors['buyer']['objectives'] = [
            'At each decision, offer to buy visible capacity minus one goods for the same number of '
            'currency units, subject to your available cash and supplier consent.']
        comparison = {'actorId': 'buyer', 'section': 'metrics', 'recordId': 'capacity', 'beforeRound': 2,
                          'afterRound': 3, 'baseline': str(initial), 'changed': str(initial + delta),
                          'before': str(initial - 1), 'after': str(initial + delta - 1), 'direction': 'increase_quantity'}
    elif domain == 'trade':
        for route, cost in [('a', variant + 1), ('b', variant + 2)]:
            catalog['order_' + route]['parameters']['transfers'][0]['amount'] = str(cost)
            catalog['order_' + route]['description'] = (
                f'Offer {cost} currency for one good through route {route.upper()}; '
                'requires current route eligibility and supplier consent.')
        catalog['restrict_a']['visibility'] = {'kind': 'actors', 'actorIds': ['regulator']}
        actors['importer']['objectives'] = ['Buy one good through the cheapest currently eligible route.']
        comparison = {'actorId': 'importer', 'section': 'rules', 'recordId': 'route_a_eligible', 'beforeRound': 2,
                          'afterRound': 3, 'baseline': True, 'changed': False, 'before': 'order_a', 'after': 'order_b',
                          'direction': 'switch_to_eligible_route'}
    else:
        # C is not a consenting party: the relation is external information.
        # A+B cannot close the vote before C records a valid opposing vote.
        catalog['coalition']['visibility'] = {'kind': 'actors', 'actorIds': ['org_a', 'org_b']}
        weights = {'org_a': str(25 + variant * 5), 'org_b': str(25 - variant * 5), 'org_c': '50'}
        threshold = str(50 + variant * 5)
        catalog['program_vote']['parameters'].update(weights=weights, threshold=threshold)
        catalog['program_vote']['description'] = (
            f'Cast your own vote. Weights A/B/C are {weights["org_a"]}/{weights["org_b"]}/50; '
            f'passage requires {threshold} and funding of 60. Coalition consent never casts a vote.')
        actors['org_c']['objectives'] = [
            'Preserve the institutional budget. Wait while no coalition exists; '
            'record your own opposing program vote when coalition_ab is allied.']
        comparison = {'actorId': 'org_c', 'section': 'relations', 'recordId': 'coalition_ab', 'beforeRound': 1,
                          'afterRound': 2, 'baseline': 'none', 'changed': 'allied', 'before': 'wait', 'after': 'oppose',
                          'direction': 'wait_then_record_opposition'}
    spec = validate_spec(spec)
    result = []
    for arm in ARMS:
        world = clone(spec)
        if arm != 'reflexive':
            world['evaluationObservationMask'] = {'schemaVersion': MASK_SCHEMA, 'maskId': pair_id}
        result.append({'evaluationId': f'{pair_id}-{arm}', 'pairId': pair_id, 'domain': domain,
                           'variant': variant, 'seed': seed, 'arm': arm, 'spec': world, 'comparison': clone(comparison)})
    return result


def build_cases() -> list[dict]:
    """Return fresh, fixed 18+18 specs. No caller-supplied variants or masks."""
    return [case for domain in DOMAINS for variant in (1, 2, 3) for seed in (0, 1)
            for case in _case_pair(domain, variant, seed)]


@lru_cache(maxsize=1)
def _mask_registry():
    # Cache serialized values so callers cannot mutate the authoritative registry.
    return {case['pairId']: canonical_json(case) for case in build_cases() if case['arm'] != 'reflexive'}


def _physical_spec(spec):
    value = clone(spec)
    value.pop('policy', None)
    for key in ('maxCostUsd', 'maxTokens', 'maxOutputTokens'):
        value.get('limits', {}).pop(key, None)
    return value


def apply_observation_mask(spec: dict, observation: dict) -> dict:
    """Mask one closed external record value before the caller computes its digest.

    No timestamps, options, own balances, messages or mandatory consent records
    are changed. Mask identity is never added to the actor payload. Reject
    arbitrary specifications, masks and post-digest use instead of failing open.
    """
    result = clone(observation)
    if 'evaluationObservationMask' not in spec:
        return result
    mask = spec['evaluationObservationMask']
    require(isinstance(mask, dict) and set(mask) == {'schemaVersion', 'maskId'}
            and mask['schemaVersion'] == MASK_SCHEMA and isinstance(mask['maskId'], str)
            and mask['maskId'] in _mask_registry(), 'invalid_evaluation_mask', 'Mask must be a closed M5 identity')
    case = json.loads(_mask_registry()[mask['maskId']])
    require(_physical_spec(spec) == _physical_spec(case['spec']),
            'invalid_evaluation_mask', 'Mask must bind the fixed M5 physical specification')
    require('observationId' not in result, 'invalid_evaluation_mask', 'Mask must be applied before observation digest')
    comparison = case['comparison']
    if result['actorId'] == comparison['actorId'] and result['round'] == comparison['afterRound']:
        result['world'][comparison['section']][comparison['recordId']]['value'] = clone(comparison['baseline'])
    return result


def _verify_mask_hook(cases):
    from .observations import build_observation

    for case in cases:
        if case['arm'] == 'reflexive':
            continue
        spec, comparison = case['spec'], case['comparison']
        before = initial_snapshot(spec)
        after = clone(before)
        after[comparison['section']][comparison['recordId']]['value'] = comparison['changed']
        for phase in ('proposal', 'response'):
            original = build_observation(spec, before, comparison['actorId'], comparison['afterRound'], phase)
            masked = build_observation(spec, after, comparison['actorId'], comparison['afterRound'], phase)
            require(original == masked, 'evaluation_hook_missing', 'Real observation builder must mask before digest')


def _source_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in (
        'evaluation.py', 'contracts.py', 'controller.py', 'examples.py', 'kernel.py',
        'observations.py', 'policy.py', 'store.py', 'service.py')}


def _manifest(pricing_spec, max_usd):
    total = decimal(max_usd, nonnegative=True)
    require(0 < total <= 25, 'evaluation_budget', 'Evaluation ceiling must be positive and at most USD25')
    require(isinstance(pricing_spec, dict) and pricing_spec.get('mode') in {'scripted', 'external'},
            'evaluation_admission', 'Explicit scripted or external pricing mode is required')
    pricing = clone(pricing_spec)
    # Authorization is bound to this manifest rather than hashed recursively.
    pricing.pop('authorization', None)
    require(set(pricing) <= {'mode', 'policy', 'maxTokensPerCase', 'maxOutputTokens', 'policyId'},
            'evaluation_admission', 'Unexpected evaluation pricing field')
    require(isinstance(pricing.get('policyId'), str) and bool(pricing['policyId'].strip()),
            'evaluation_admission', 'A stable policy implementation identity is required')
    cases = build_cases()
    share = (total / len(cases)).quantize(Decimal('0.000000000001'), rounding=ROUND_FLOOR)
    require(share > 0, 'evaluation_budget', 'Ceiling cannot fund a positive case share')
    for case in cases:
        limits = case['spec']['limits']
        limits.update(maxCostUsd=quantity(share), maxTokens=pricing.get('maxTokensPerCase', 250000),
                      maxOutputTokens=pricing.get('maxOutputTokens', 4096))
        require(type(limits['maxOutputTokens']) is int and 1 <= limits['maxOutputTokens'] <= 8192,
                'evaluation_admission', 'Evaluation output bound is at most 8192 tokens per request')
        if pricing['mode'] == 'external':
            require(isinstance(pricing.get('policy'), dict), 'evaluation_admission', 'Pinned HTTP policy is required')
            case['spec']['policy'] = clone(pricing['policy'])
        else:
            require('policy' not in pricing, 'evaluation_admission', 'Scripted mode cannot configure an HTTP provider')
        case['spec'] = validate_spec(case['spec'])
    manifest = {'schemaVersion': VERSION, 'pricing': pricing, 'cases': cases, 'rubric': clone(RUBRIC),
                    'maxCostUsd': quantity(total), 'caseShareUsd': quantity(share),
                    'allocatedUsd': quantity(share * len(cases)), 'sourceHashes': _source_hashes(),
                    'comparisonRule': 'All 18 preregistered paired contrasts must pass separately.',
                    'domainThresholdPercent': 80, 'maxPointsPerCase': 8,
                    'explanationReview': 'Independent qualitative review required; automatic rationale presence is not verification.',
                    'calibrationClaim': False}
    manifest['manifestHash'] = digest(manifest)
    return manifest


def preregister(pricing_spec: dict, max_usd='25') -> dict:
    """Build the exact launch manifest for offline review, without calling a factory."""
    return _manifest(pricing_spec, max_usd)


def _admit(pricing, manifest, factory):
    mode = manifest['pricing']['mode']
    require(callable(factory) and getattr(factory, 'evaluation_mode', None) == mode,
            'evaluation_admission', 'Factory must explicitly declare its evaluation_mode')
    if mode == 'external':
        authorization = pricing.get('authorization', {})
        require(isinstance(authorization, dict) and authorization.get('pricingVerified') is True
                and authorization.get('offlineGatesPassed') is True
                and authorization.get('manifestHash') == manifest['manifestHash']
                and isinstance(authorization.get('coordinator'), str) and bool(authorization['coordinator'].strip())
                and isinstance(authorization.get('evidenceRefs'), list) and bool(authorization['evidenceRefs'])
                and all(isinstance(ref, str) and ref.strip() for ref in authorization['evidenceRefs']),
                'evaluation_not_authorized', 'Coordinator must bind verified USD pricing and offline gates to this manifest')


def _read(path):
    require(not path.is_symlink(), 'evaluation_artifact', 'Evaluation artifacts cannot be symlinks')
    return json.loads(path.read_text())


def _write(path, value):
    require(not path.is_symlink(), 'evaluation_artifact', 'Evaluation artifacts cannot be symlinks')
    temporary = path.with_suffix(path.suffix + '.pending')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(canonical_json(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def _batch_lock(root):
    root = Path(root).absolute()
    require(not any(path.is_symlink() for path in [root, *root.parents]),
            'evaluation_artifact', 'Evaluation output cannot traverse a symlink')
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root / '.evaluation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorldError('evaluation_busy', 'Another evaluator owns this output directory') from None
        yield root
    finally:
        os.close(fd)


def _bind_external_policy(policy, spec):
    from .policy import StrictHTTPPolicy

    require(type(policy) is StrictHTTPPolicy, 'evaluation_admission', 'External runs require the strict HTTP policy')
    config, limits = spec['policy'], spec['limits']
    tariff = config['pricing']
    expected = {
        'provider': config['provider'], 'model': config['model'], 'base_url': config['baseUrl'].rstrip('/'),
        'pricing': tariff, 'max_input': config['maxInputTokens'], 'max_output': limits['maxOutputTokens'],
        'timeout': config['timeoutSeconds'], 'context': tariff['contextWindowTokens'],
        '_input_rate': decimal(tariff['inputUsdPerMillion']), '_output_rate': decimal(tariff['outputUsdPerMillion']),
        '_overhead': tariff['inputOverheadTokens'], '_output_parameter': tariff['outputTokenParameter'],
        '_reasoning_effort': config.get('reasoningEffort'),
        'max_intents': limits['maxIntentsPerPhase'], '_max_messages': limits['maxInboxItems'],
        '_max_message_chars': limits['maxMessageChars'], '_actors': frozenset(a['actorId'] for a in spec['actors']),
    }
    require(all(getattr(policy, field, None) == value for field, value in expected.items()),
            'evaluation_policy_mismatch', 'Effective HTTP policy must match all pinned pricing and request bounds')


class _ReservedPolicy:
    """Validate bounded quotes and record calls; the store admits dispatches.

    The controller reserves transactionally before decide. Known usage releases
    unused allowance; unknown and in-flight attempts retain their full quotes.
    Cumulative reservation quotes are audit telemetry, not a spending ceiling.
    """

    def __init__(self, policy, spec, mode):
        self.policy = policy
        self.external = bool(getattr(policy, 'external', False))
        self.supports_feedback = getattr(policy, 'supports_feedback', False) is True
        self._lock = threading.Lock()
        self.calls = []
        if mode == 'external':
            _bind_external_policy(policy, spec)
        else:
            require(getattr(policy, 'evaluation_mode', None) == 'scripted', 'evaluation_admission',
                    'Scripted policy must explicitly attest no external dispatches')

    def reservation(self, observation, *, feedback=None):
        kwargs = {'feedback': feedback} if self.supports_feedback else {}
        reservation = self.policy.reservation(observation, **kwargs)
        cost = decimal(reservation['costUsd'], nonnegative=True)
        require(type(reservation['tokens']) is int and reservation['tokens'] > 0 and cost > 0,
                'unbounded_transport', 'Metered policy must reserve positive complete exposure')
        return reservation

    def decide(self, observation, *, feedback=None):
        start = time.monotonic_ns()
        try:
            kwargs = {'feedback': feedback} if self.supports_feedback else {}
            return self.policy.decide(observation, **kwargs)
        finally:
            with self._lock:
                self.calls.append({'slot': slot_id(observation['round'], observation['phase'], observation['actorId']),
                                   'elapsedNs': time.monotonic_ns() - start})


def _trace(store):
    records = []
    for period in store.rounds():
        for decision in period['decisions']:
            slot = slot_id(decision['round'], decision['phase'], decision['actorId'])
            records.append({'slot': slot, 'observation': store.observation(slot), 'decision': decision})
    return {'head': store.head(), 'history': store.history(), 'rounds': store.rounds(), 'records': records}


def _action_value(domain, decision):
    intents = decision['intents']
    if domain == 'coalition' and not intents:
        return 'wait'
    if len(intents) != 1:
        return None
    intent = intents[0]
    if domain == 'investment' and intent['templateId'] == 'purchase' and intent['operation'] == 'propose':
        parameters = intent['parameters']
        try:
            amount = quantity(parameters.get('quantity'))
            return amount if decimal(parameters.get('price')) == decimal(amount) else None
        except WorldError:
            return None
    if domain == 'trade' and intent['templateId'] in {'order_a', 'order_b'} and intent['operation'] == 'propose':
        return intent['templateId']
    if domain == 'coalition' and intent['templateId'] == 'program_vote' and intent['operation'] == 'execute':
        return 'oppose' if intent['parameters'].get('support') is False else 'support'
    return None


def _focal(case, trace):
    comparison = case['comparison']
    return [next((record for record in trace['records'] if record['slot'] ==
                  slot_id(epoch, 'proposal', comparison['actorId'])), None)
            for epoch in (comparison['beforeRound'], comparison['afterRound'])]


def _score(case, trace):
    """Small deterministic checks over committed receipts, with explicit limits."""
    comparison = case['comparison']
    before, after = _focal(case, trace)
    require(before is not None and after is not None, 'evaluation_evidence', 'Comparison receipts are missing')
    for record in trace['records']:
        obs, decision = record['observation'], record['decision']
        require(obs is not None and decision['observationId'] == obs['observationId']
                and obs['observationId'] == digest({k: v for k, v in obs.items() if k != 'observationId'}),
                'evaluation_evidence', 'Decision does not bind its visible observation')
    for snapshot in trace['history']:
        validate_snapshot(case['spec'], snapshot)
    expected_after = comparison['after'] if case['arm'] == 'reflexive' else comparison['before']
    matches = [_action_value(case['domain'], before['decision']) == comparison['before'],
               _action_value(case['domain'], after['decision']) == expected_after]
    history = {snapshot['round']: snapshot for snapshot in trace['history']}
    record_value = lambda epoch: history[epoch - 1][comparison['section']][comparison['recordId']]['value']
    stimulus = (record_value(comparison['beforeRound']) == comparison['baseline']
                and record_value(comparison['afterRound']) == comparison['changed'])
    resolutions = [item for period in trace['rounds'] for item in period['resolutions']]
    intent_ids = [intent['intentId'] for record in trace['records'] for intent in record['decision']['intents']]
    require(sorted(intent_ids) == sorted(item['intentId'] for item in resolutions),
            'evaluation_evidence', 'Committed intents and resolution receipts must match exactly')
    rejected = sum(not item['accepted'] for item in resolutions)
    feasible = 2 if not rejected else (1 if rejected * 5 <= len(resolutions) else 0)
    return {
        'points': {'goalConsistency': sum(matches), 'feasibility': feasible,
                   'consequenceResponse': (1 + int(matches[0])) if stimulus and matches[1] else 0,
                   'explanationRecord': None},
        'stimulusPresent': stimulus, 'observedActions': [_action_value(case['domain'], r['decision']) for r in (before, after)],
        'evidenceRefs': [{'slot': r['slot'], 'observationId': r['observation']['observationId'],
                          'decisionId': r['decision']['decisionId']} for r in (before, after)],
        'rejectedIntents': rejected, 'totalIntents': len(resolutions),
        'abstentions': sum(not r['decision']['intents'] for r in trace['records']),
        'explanationReview': 'pending_independent_qualitative_review', 'hardValidity': 'committed_store_checks_only',
    }


def _empty_budget():
    return {key: {'tokens': 0, 'costUsd': '0'} for key in ('reserved', 'actual', 'unknown', 'exposure')} | {'attempts': []}


def _committed_operations(rounds):
    resolutions = [item for period in rounds for item in period['resolutions']]
    decisions = [item for period in rounds for item in period['decisions']]
    return {
        'totalCommittedIntents': len(resolutions),
        'rejectedCommittedIntents': sum(not item['accepted'] for item in resolutions),
        'committedAbstentions': sum(not item['intents'] for item in decisions),
    }


def _execute(root, case, factory, mode):
    case_dir = root / case['evaluationId']
    require(not case_dir.exists(), 'evaluation_artifact', 'Existing case data cannot start a new attempt')
    case_dir.mkdir()
    receipt = {'evaluationId': case['evaluationId'], 'status': 'failed', 'budget': _empty_budget(),
                   'score': None, 'errorCode': None, 'calls': [], 'completedRound': 0}
    policy = candidate = None
    with WorldStore(case_dir / 'world.sqlite3', case['spec']) as store:
        fence = store.acquire_writer('bounded-evaluation')
        try:
            candidate = factory(clone(case['spec']))
            policy = _ReservedPolicy(candidate, case['spec'], mode)
            run_to_horizon(store, policy, fence)
            trace = _trace(store)
            _write(case_dir / 'trace.json', trace)
            receipt.update(status='completed', traceHash=digest(trace), score=_score(case, trace))
        except Exception as error:
            code = error.code if isinstance(error, WorldError) else 'policy_or_evaluation_failure'
            receipt.update(status='budget_stopped' if code in {'evaluation_budget', 'run_budget_exhausted',
                           'attempt_budget_exhausted'} else 'failed', errorCode=code)
            # The controller sets these sanitized validator literals only when
            # the original attempt allowance is exhausted. Never stringify a
            # provider/unknown exception or retain arbitrary detail payloads.
            if (isinstance(error, WorldError) and code == 'required_decision_failed'
                    and isinstance(error.details, dict)):
                details = {key: error.details[key] for key in ('lastErrorCode', 'lastErrorMessage')
                           if isinstance(error.details.get(key), str)}
                if details:
                    receipt['errorDetails'] = details
        finally:
            receipt.update(budget=store.budget_summary(), completedRound=store.head()['round'],
                           calls=policy.calls if policy else [], operations=_committed_operations(store.rounds()))
            store.release_writer(fence)
            if candidate and callable(getattr(candidate, 'close', None)):
                try:
                    candidate.close()
                except Exception:
                    receipt['closeError'] = True
    _write(case_dir / 'receipt.json', receipt)
    return receipt


def _load_receipts(root, manifest, state):
    require(manifest.get('schemaVersion') == VERSION
            and manifest.get('manifestHash') == digest({k: v for k, v in manifest.items() if k != 'manifestHash'})
            and state.get('manifestHash') == manifest['manifestHash']
            and set(state.get('cases', {})) == {c['evaluationId'] for c in manifest['cases']},
            'evaluation_evidence', 'Manifest and status must bind the entire frozen matrix')
    result = {}
    for case in manifest['cases']:
        cid = case['evaluationId']
        entry = state['cases'][cid]
        require(entry.get('status') in {'planned', 'running', 'interrupted', 'completed', 'failed', 'budget_stopped'},
                'evaluation_evidence', 'Unrecognized durable case status')
        if entry['status'] == 'planned':
            continue
        path = root / cid / 'receipt.json'
        if entry['status'] in {'running', 'interrupted'} and 'receiptHash' not in entry:
            budget = _empty_budget()
            for key in ('reserved', 'unknown', 'exposure'):
                budget[key] = {'costUsd': manifest['caseShareUsd'], 'tokens': case['spec']['limits']['maxTokens']}
            result[cid] = {'evaluationId': cid, 'status': 'interrupted', 'budget': budget,
                               'score': None, 'calls': [], 'completedRound': None, 'budgetBasis': 'full_share_uncertain'}
        elif path.exists():
            receipt = _read(path)
            require(entry.get('receiptHash') == digest(receipt) and receipt['status'] == entry['status']
                    and receipt['evaluationId'] == cid, 'evaluation_evidence', 'Case receipt binding changed')
            if receipt['status'] == 'completed':
                trace = _read(root / cid / 'trace.json')
                require(receipt['traceHash'] == digest(trace) and receipt['score'] == _score(case, trace),
                        'evaluation_evidence', 'Completed trace or deterministic score changed')
            result[cid] = receipt
        else:
            raise WorldError('evaluation_evidence', 'A terminal receipt is missing; preserve data and investigate')
    return result


def _qualitative_scores(root, manifest, receipts):
    path = root / 'qualitative-review.json'
    if not path.exists():
        return {}
    review = _read(path)
    require(review.get('manifestHash') == manifest['manifestHash'] and isinstance(review.get('reviews'), list),
            'evaluation_review', 'Qualitative review must bind the frozen manifest')
    result = {}
    for item in review['reviews']:
        cid = item.get('evaluationId')
        receipt = receipts.get(cid)
        require(cid not in result and receipt is not None and receipt['status'] == 'completed'
                and item.get('traceHash') == receipt.get('traceHash')
                and type(item.get('score')) is int and 0 <= item['score'] <= 2
                and item.get('reviewerType') in {'human', 'independent-agent'}
                and isinstance(item.get('reviewer'), str) and bool(item['reviewer'].strip())
                and isinstance(item.get('note'), str) and bool(item['note'].strip()),
                'evaluation_review', 'Qualitative score requires a typed named reviewer, note and exact completed evidence')
        ids = {ref['decisionId'] for ref in receipt['score']['evidenceRefs']}
        require(isinstance(item.get('evidenceRefs'), list) and set(item['evidenceRefs']) == ids,
                'evaluation_review', 'Review must cite both comparison decisions')
        result[cid] = item['score']
    return result


def _group_report(cases, receipts, qualitative):
    complete, reviewed, points = 0, 0, 0
    for case in cases:
        cid = case['evaluationId']
        receipt = receipts.get(cid)
        if receipt is None or receipt['status'] != 'completed':
            continue
        complete += 1
        points += sum(score for score in receipt['score']['points'].values() if score is not None)
        if cid in qualitative:
            reviewed += 1
            points += qualitative[cid]
    maximum = len(cases) * 8
    finished = complete == reviewed == len(cases)
    return {'plannedCases': len(cases), 'completedCases': complete, 'incompleteCases': len(cases) - complete,
                'qualitativeReviewedCases': reviewed, 'earnedPoints': points, 'denominatorPoints': maximum,
                'percentLowerBound': quantity((Decimal(points) * 100 / maximum).quantize(Decimal('0.01'), rounding=ROUND_FLOOR)),
                'thresholdPercent': 80, 'status': ('passed' if points * 100 >= maximum * 80 else 'failed')
                if finished else 'incomplete'}


def _distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {'count': 0, 'min': None, 'median': None, 'p95': None, 'max': None}
    return {'count': len(ordered), 'min': ordered[0], 'median': ordered[(len(ordered) - 1) // 2],
                'p95': ordered[(len(ordered) * 95 + 99) // 100 - 1], 'max': ordered[-1]}


def _operational_report(cases, receipts):
    known = [receipts[c['evaluationId']] for c in cases if c['evaluationId'] in receipts]
    attempts = [a for r in known for a in r['budget']['attempts']]
    operations = [r['operations'] for r in known if 'operations' in r]
    return {'knownAttempts': len(attempts), 'knownRetries': sum(a['ordinal'] > 1 for a in attempts),
                'unobservedCases': len(cases) - len(operations),
                'rejectedCommittedIntents': sum(op['rejectedCommittedIntents'] for op in operations),
                'totalCommittedIntents': sum(op['totalCommittedIntents'] for op in operations),
                'committedAbstentions': sum(op['committedAbstentions'] for op in operations),
                'callElapsedNs': _distribution([c['elapsedNs'] for r in known for c in r['calls']]),
                'reservedTokensPerAttempt': _distribution([a['reserved']['tokens'] for a in attempts]),
                'measuredTokensPerAttempt': _distribution([a['usage']['tokens'] for a in attempts
                                                       if a['status'] in {'succeeded', 'failed'}]),
                'unknownAttempts': sum(a['status'] == 'unknown' for a in attempts)}


def _contrasts(cases, receipts):
    contrasts = []
    for case in cases:
        if case['arm'] != 'reflexive':
            continue
        comparison = case['comparison']
        pair = [receipts.get(f'{case["pairId"]}-{arm}') for arm in ARMS]
        complete = all(r is not None and r['status'] == 'completed' for r in pair)
        passed = complete and all(r['score']['stimulusPresent'] for r in pair)
        if passed:
            passed = (pair[0]['score']['observedActions'] == [comparison['before'], comparison['after']]
                      and pair[1]['score']['observedActions'] == [comparison['before'], comparison['before']]
                      and comparison['before'] != comparison['after'])
        contrasts.append({'pairId': case['pairId'], 'domain': case['domain'], 'comparison': clone(comparison),
                              'status': ('passed' if passed else 'failed') if complete else 'incomplete',
                              'evidenceRefs': [r['score']['evidenceRefs'] for r in pair] if complete else []})
    return contrasts


def _summarize(root, manifest, state):
    receipts = _load_receipts(root, manifest, state)
    qualitative = _qualitative_scores(root, manifest, receipts)
    domains = {}
    for domain in DOMAINS:
        cases = [c for c in manifest['cases'] if c['domain'] == domain]
        domains[domain] = _group_report(cases, receipts, qualitative)
        domains[domain]['arms'] = {arm: _group_report([c for c in cases if c['arm'] == arm], receipts, qualitative) for arm in ARMS}
        domains[domain]['operations'] = _operational_report(cases, receipts)
    contrasts = _contrasts(manifest['cases'], receipts)
    totals = {key: {'costUsd': quantity(sum((decimal(r['budget'][key]['costUsd']) for r in receipts.values()), Decimal(0))),
                    'tokens': sum(r['budget'][key]['tokens'] for r in receipts.values())}
              for key in ('reserved', 'actual', 'unknown', 'exposure')}
    require(decimal(totals['exposure']['costUsd']) <= decimal(manifest['allocatedUsd']),
            'evaluation_budget', 'Batch actual plus unknown/in-flight exposure exceeds fixed allocation')
    attempts = [a for receipt in receipts.values() for a in receipt['budget']['attempts']]
    report = {'schemaVersion': VERSION, 'manifestHash': manifest['manifestHash'], 'mode': manifest['pricing']['mode'],
                  'domains': domains, 'requiredContrasts': contrasts, 'budget': totals,
                  'allocatedUsd': manifest['allocatedUsd'], 'maxCostUsd': manifest['maxCostUsd'],
                  'cases': {case['evaluationId']: receipts.get(case['evaluationId'], {'status': 'missing'})['status']
                         for case in manifest['cases']},
                  'attempts': len(attempts), 'retries': sum(a['ordinal'] > 1 for a in attempts),
                  'calibrationClaim': False, 'liveModelRealismClaim': False,
                  'qualitativeReview': 'Independent qualitative explanation review and hard-validity/privacy review remain required.'}
    report['rubricGate'] = ('incomplete' if any(d['status'] == 'incomplete' for d in domains.values()) else
                            'passed' if all(d['status'] == 'passed' and d['arms']['reflexive']['status'] == 'passed'
                                            for d in domains.values()) else 'failed')
    report['contrastGate'] = ('incomplete' if any(c['status'] == 'incomplete' for c in contrasts) else
                             'passed' if all(c['status'] == 'passed' for c in contrasts) else 'failed')
    report['promotionAuthorized'] = False
    _write(root / 'report.json', report)
    return report


def summarize_evaluation(outputdir) -> dict:
    """Refresh reports after independent qualitative review; never dispatch or resume."""
    with _batch_lock(outputdir) as root:
        return _summarize(root, _read(root / 'preregistration.json'), _read(root / 'status.json'))


def run_evaluation(outputdir, policy_factory, pricing_spec, max_usd='25') -> dict:
    """Run each fixed case at most once with a nontransferable share of <=USD25.

    A prior running case becomes interrupted, retaining its whole share. Failed,
    stopped and completed cases are terminal; a repeated invocation never calls
    their factory. New output directories represent new budgets, so the caller
    must use the same authorized directory; this is not an account-wide ledger.
    """
    manifest = _manifest(pricing_spec, max_usd)
    _admit(pricing_spec, manifest, policy_factory)
    _verify_mask_hook(manifest['cases'])
    with _batch_lock(outputdir) as root:
        manifest_path, state_path = root / 'preregistration.json', root / 'status.json'
        if manifest_path.exists():
            require(_read(manifest_path) == manifest, 'evaluation_manifest_conflict', 'Frozen evaluation inputs changed')
            state = _read(state_path)
            require(state.get('manifestHash') == manifest['manifestHash']
                    and set(state.get('cases', {})) == {c['evaluationId'] for c in manifest['cases']},
                    'evaluation_evidence', 'Batch status does not bind the frozen matrix')
            for entry in state['cases'].values():
                if entry['status'] == 'running':
                    entry['status'] = 'interrupted'
            _write(state_path, state)
            _load_receipts(root, manifest, state)  # Fail closed before new work if old evidence is lost.
        else:
            require({p.name for p in root.iterdir()} == {'.evaluation.lock'},
                    'evaluation_artifact', 'Refuse to reset a nonempty evaluation directory')
            _write(manifest_path, manifest)
            state = {'manifestHash': manifest['manifestHash'], 'authorization': clone(pricing_spec.get('authorization')),
                         'cases': {
                c['evaluationId']: {'status': 'planned'} for c in manifest['cases']}}
            _write(state_path, state)
        for case in manifest['cases']:
            cid = case['evaluationId']
            if state['cases'][cid]['status'] != 'planned':
                continue
            state['cases'][cid] = {'status': 'running'}
            _write(state_path, state)
            receipt = _execute(root, case, policy_factory, manifest['pricing']['mode'])
            state['cases'][cid] = {'status': receipt['status'], 'receiptHash': digest(receipt)}
            _write(state_path, state)
        return _summarize(root, manifest, state)
