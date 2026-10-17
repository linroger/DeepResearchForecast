"""Directed replay of six preserved actor contexts, never a full behavior gate.

Each of two repetitions makes one revision RPC against an already captured
candidate. A durable before-dispatch journal prevents retrying any consumed row.
"""
from decimal import Decimal
import hashlib
from pathlib import Path

from .artifacts import atomic_json, read_json
from .contracts import WorldError, canonical_json, clone, decimal, digest, quantity, require, validate_decision
from .evaluation import _batch_lock, _bind_external_policy, _source_hashes
from .review import REVIEW_MODES, assessment_status, review_mode, validate_assessment

VERSION = 'world-consistency-replay/v1'
FIXTURE = Path(__file__).resolve().parents[3] / 'tests/fixtures/world_consistency_cases.json'

_ASSESSMENT_ERRORS = frozenset({
    'Revision requires a typed consistency assessment',
    'Revision must assess all four consistency dimensions',
    'Unsupported assessment check fields',
    'Assessment kinds must be complete and unique',
    'Assessment indexes must identify actual unique records',
    'Goal review must reference every supplied objective',
    'Explanation review must reference every final intent',
    'Each assessment needs a bounded explanation',
    'Assessment needs bounded visible evidence references',
    'Assessment evidence must refer to the original observation',
    'Assessment evidence path is unavailable',
    'Assessment evidence index is unavailable',
    'Assessment evidence path does not resolve',
    'Per-check review requires checks without aggregate status',
    'Each check requires an explicit consistency verdict',
})
_GENERIC_FAILURE = 'The bounded revision did not produce an admissible response.'
_REVIEW_SHAPE_ERRORS = frozenset({'invalid_review_response', 'invalid_assessment'})


def _error_message(error):
    # Preserve only fixed validator vocabulary, never opaque provider/model text.
    if isinstance(error, WorldError) and error.code == 'invalid_assessment' and str(error) in _ASSESSMENT_ERRORS:
        return str(error)
    if isinstance(error, WorldError) and error.code == 'policy_transport_failed':
        from .policy import _TRANSPORT_FAILURE_MESSAGES
        if str(error) in _TRANSPORT_FAILURE_MESSAGES:
            return str(error)
    return _GENERIC_FAILURE


def preregister(pricing_spec, max_usd='1.25', *, evaluation_version=VERSION):
    require(evaluation_version == VERSION, 'evaluation_version', 'Unknown directed replay version')
    pricing = clone(pricing_spec)
    pricing.pop('authorization', None)
    require(set(pricing) <= {'mode', 'policy', 'maxTokensPerCase', 'maxOutputTokens', 'policyId'}
            and pricing.get('mode') == 'external' and review_mode(pricing) in REVIEW_MODES,
            'evaluation_admission', 'Directed replay requires pinned actor consistency review')
    maximum = decimal(max_usd, nonnegative=True)
    require(0 < maximum <= Decimal('1.25'), 'evaluation_budget', 'Directed replay ceiling is at most USD1.25')
    fixture = read_json(FIXTURE)
    require(len(fixture['cases']) == 6, 'evaluation_evidence', 'Six fixed contexts are required')
    cases = []
    for repeat in range(2):
        for source in fixture['cases']:
            spec = clone(source['analystOnly']['originalSpec'])
            spec['policy'] = clone(pricing['policy'])
            spec['limits']['maxOutputTokens'] = pricing['maxOutputTokens']
            payload = clone(source['actorPayload'])
            require(digest(payload) == source['provenance']['actorPayloadHash'],
                    'evaluation_evidence', 'Captured actor input changed')
            cases.append({'caseId': source['caseId'], 'repeat': repeat,
                          'evaluationId': f"{source['caseId']}-r{repeat}", 'actorPayload': payload, 'spec': spec})
    hashes = _source_hashes()
    hashes[Path(__file__).name] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest = {'schemaVersion': VERSION, 'pricing': pricing, 'maxCostUsd': quantity(maximum),
                'allocatedUsd': quantity(maximum),
                'sourceHashes': hashes, 'fixtureSha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                'cases': cases, 'requiredCases': 12, 'requiredMatches': 12,
                'criteria': 'Correct both retained defects and retain consequential choices in four controls, twice each.',
                'scope': 'Directed revision of saved candidates; not fresh generation, a full world run, holdout or calibration.',
                'promotionAuthorized': False}
    manifest['manifestHash'] = digest(manifest)
    return manifest


def _actions(observation, decision):
    kinds = {v['templateId']: v['kind'] for v in observation['options']}
    return [{k: v for k, v in intent.items() if k not in {'actorId', 'intentId', 'phase', 'priority'}}
            for intent in decision['intents'] if kinds.get(intent['templateId']) != 'message']


def _matches(case, decision):
    obs = case['actorPayload']['observation']
    actions = _actions(obs, decision)
    if case['caseId'] == 'investment-rationale-action-disagreement':
        return len(actions) == 1 and actions[0].get('templateId') == 'purchase' and actions[0].get('operation') == 'propose' \
            and actions[0].get('parameters') == {'quantity': '2', 'price': '2'}
    if case['caseId'] == 'coalition-opposition-before-trigger':
        return actions == []
    return actions == _actions(obs, case['actorPayload']['candidateDecision'])


def _validate_manifest(manifest):
    require(isinstance(manifest, dict) and manifest.get('schemaVersion') == VERSION
            and manifest.get('manifestHash') == digest({k: v for k, v in manifest.items() if k != 'manifestHash'})
            and isinstance(manifest.get('cases'), list) and len(manifest['cases']) == 12,
            'evaluation_evidence', 'Directed replay manifest identity or schema changed')
    require(all(isinstance(case, dict) and isinstance(case.get('evaluationId'), str) for case in manifest['cases'])
            and len({case['evaluationId'] for case in manifest['cases']}) == 12,
            'evaluation_evidence', 'Directed replay case identities changed')


def _revalidate_saved_decision(case, value):
    obs = case['actorPayload']['observation']
    require(isinstance(value, dict) and isinstance(value.get('intents'), list)
            and all(isinstance(item, dict) for item in value['intents']),
            'evaluation_evidence', 'Saved decision must be a normalized object')
    raw = {k: v for k, v in value.items() if k not in {'round', 'phase', 'decisionId'}}
    raw['intents'] = [{k: v for k, v in item.items() if k not in {'actorId', 'intentId', 'phase'}}
                      for item in raw['intents']]
    require(validate_decision(case['spec'], raw, obs['actorId'], obs, phase=obs['phase']) == value,
            'evaluation_evidence', 'Saved revised decision binding changed')


def _withheld_review(manifest, case, decision, assessment):
    """Private evidence of a validated refusal, never an admitted decision."""
    value = {'schemaVersion': 'world-withheld-review/v1', 'manifestHash': manifest['manifestHash'],
             'evaluationId': case['evaluationId'],
             'observationHash': digest(case['actorPayload']['observation']),
             'candidateHash': digest(case['actorPayload']['candidateDecision']),
             'decision': clone(decision), 'assessment': clone(assessment)}
    value['receiptHash'] = digest(value)
    return value


def _validate_withheld_review(manifest, case, row):
    value = row['withheldReview']
    fields = {'schemaVersion', 'manifestHash', 'evaluationId', 'observationHash',
              'candidateHash', 'decision', 'assessment', 'receiptHash'}
    require(row['status'] == 'failed' and row.get('usage') is not None
            and row.get('errorCode') == 'consistency_unresolved'
            and set(row) == {'status', 'reservation', 'usage', 'errorCode', 'errorMessage', 'withheldReview'}
            and isinstance(value, dict) and set(value) == fields,
            'evaluation_evidence', 'Withheld review must remain private failed evidence')
    require(value == _withheld_review(manifest, case, value['decision'], value['assessment']),
            'evaluation_evidence', 'Withheld review input or content binding changed')
    _revalidate_saved_decision(case, value['decision'])
    assessment = validate_assessment(value['assessment'], case['actorPayload']['observation'], value['decision'],
                                     mode=review_mode(case['spec']))
    require(assessment_status(assessment, mode=review_mode(case['spec'])) == 'unresolved',
            'evaluation_evidence', 'Withheld review must retain its unresolved assessment')


def _review_shape(manifest, case, error_code, usage, shape):
    """Bind validated structural evidence to server-owned dispatch identities."""
    from .review import validate_revision_shape

    value = {'schemaVersion': 'world-review-shape-diagnostic/v1', 'manifestHash': manifest['manifestHash'],
             'evaluationId': case['evaluationId'], 'purpose': 'revision',
             'observationHash': digest(case['actorPayload']['observation']),
             'candidateHash': digest(case['actorPayload']['candidateDecision']),
             'errorCode': error_code, 'usage': clone(usage), 'shape': validate_revision_shape(shape)}
    value['receiptHash'] = digest(value)
    return value


def _optional_review_shape(manifest, case, row, error):
    """A diagnostic failure must never replace the original metered failure."""
    try:
        from .policy import revision_shape_diagnostic
        from .review import MODE_V3

        if (review_mode(case['spec']) != MODE_V3 or row['status'] != 'failed' or row.get('usage') is None
                or not isinstance(row.get('errorCode'), str) or row['errorCode'] not in _REVIEW_SHAPE_ERRORS or 'withheldReview' in row
                or getattr(error, 'code', None) != row['errorCode']
                or canonical_json(getattr(error, 'usage', None)) != canonical_json(row['usage'])):
            return None
        shape = revision_shape_diagnostic(error)
        if shape is None:
            return None
        return _review_shape(manifest, case, row['errorCode'], row['usage'], shape)
    except Exception:
        # Deliberately optional: do not log opaque error text or retry dispatch.
        return None


def _validate_review_shape(manifest, case, row):
    from .review import MODE_V3

    value = row['reviewShape']
    fields = {'schemaVersion', 'manifestHash', 'evaluationId', 'purpose', 'observationHash',
              'candidateHash', 'errorCode', 'usage', 'shape', 'receiptHash'}
    require(review_mode(case['spec']) == MODE_V3 and row['status'] == 'failed'
            and row.get('usage') is not None and isinstance(row.get('errorCode'), str) and row['errorCode'] in _REVIEW_SHAPE_ERRORS
            and set(row) == {'status', 'reservation', 'usage', 'errorCode', 'errorMessage', 'reviewShape'}
            and isinstance(value, dict) and set(value) == fields,
            'evaluation_evidence', 'Review shape must remain private known-metered v3 failure evidence')
    expected = _review_shape(manifest, case, row['errorCode'], row['usage'], value['shape'])
    # Canonical comparison rejects bool/int substitutions as well as digest and
    # identity mismatches; Python container equality alone would coerce them.
    require(canonical_json(value) == canonical_json(expected),
            'evaluation_evidence', 'Review shape input, usage or content binding changed')


def _validate_journal(manifest, journal):
    _validate_manifest(manifest)
    expected = {case['evaluationId'] for case in manifest['cases']}
    require(journal.get('manifestHash') == manifest['manifestHash']
            and isinstance(journal.get('cases'), dict) and set(journal['cases']) == expected,
            'evaluation_evidence', 'Directed replay journal identities changed')
    for row in journal['cases'].values():
        require(isinstance(row, dict) and isinstance(row.get('status'), str) and row['status'] in {
            'planned', 'budget_stopped', 'provider_stopped', 'unknown', 'failed', 'completed'},
            'evaluation_evidence', 'Directed replay status is invalid')
        if 'errorMessage' in row:
            require(row['status'] in {'unknown', 'failed'} and isinstance(row['errorMessage'], str)
                    and _error_message(WorldError(row.get('errorCode'), row['errorMessage'])) == row['errorMessage'],
                    'evaluation_evidence', 'Replay diagnostic must use fixed safe vocabulary')
        consumed = row['status'] in {'unknown', 'failed', 'completed'}
        require(('reservation' in row) == consumed and ('usage' in row) == consumed,
                'evaluation_evidence', 'Consumed request allowance cannot become planned')
        if consumed:
            reserve, usage = row['reservation'], row['usage']
            require(isinstance(reserve, dict) and set(reserve) == {'tokens', 'costUsd'}
                    and type(reserve.get('tokens')) is int and reserve['tokens'] > 0
                    and decimal(reserve['costUsd'], nonnegative=True) > 0,
                    'evaluation_evidence', 'Invalid replay reservation')
            require((usage is None) == (row['status'] == 'unknown'),
                    'evaluation_evidence', 'Replay metering state is inconsistent')
            if usage is not None:
                require(isinstance(usage, dict) and set(usage) == {'tokens', 'costUsd'}
                        and type(usage.get('tokens')) is int and 0 <= usage['tokens'] <= reserve['tokens']
                        and Decimal(0) <= decimal(usage['costUsd']) <= decimal(reserve['costUsd']),
                        'evaluation_evidence', 'Replay usage exceeds the saved reservation')
        if row['status'] == 'completed':
            require(set(row) == {'status', 'reservation', 'usage', 'decision', 'assessment', 'matches'},
                    'evaluation_evidence', 'Completed replay record shape changed')
    for case in manifest['cases']:
        row = journal['cases'][case['evaluationId']]
        if 'withheldReview' in row:
            _validate_withheld_review(manifest, case, row)
        if 'reviewShape' in row:
            _validate_review_shape(manifest, case, row)
        if row['status'] == 'completed':
            obs = case['actorPayload']['observation']
            value = row['decision']
            _revalidate_saved_decision(case, value)
            assessment = validate_assessment(row['assessment'], obs, value, mode=review_mode(case['spec']))
            require(assessment_status(assessment, mode=review_mode(case['spec'])) == 'clear'
                    and type(row['matches']) is bool and row['matches'] == _matches(case, value),
                    'evaluation_evidence', 'Saved revision assessment or diagnostic score changed')


def _summarize(root, manifest, journal):
    _validate_journal(manifest, journal)
    reviewed = {}
    review_path = root / 'qualitative-review.json'
    if review_path.exists():
        review = read_json(review_path)
        require(review.get('manifestHash') == manifest['manifestHash'] and isinstance(review.get('reviews'), list),
                'evaluation_review', 'Review manifest changed')
        for item in review['reviews']:
            row = journal['cases'].get(item.get('evaluationId'))
            require(row is not None and row['status'] == 'completed'
                    and item.get('resultHash') == digest(row) and type(item.get('passed')) is bool
                    and item.get('reviewerType') == 'independent-agent'
                    and isinstance(item.get('reviewer'), str) and bool(item['reviewer'].strip())
                    and isinstance(item.get('note'), str) and bool(item['note'].strip()) and item['evaluationId'] not in reviewed,
                    'evaluation_review', 'Review must bind one complete directed result')
            reviewed[item['evaluationId']] = item['passed']
    rows = list(journal['cases'].values())
    actual = sum((decimal(r['usage']['costUsd']) for r in rows if r.get('usage') is not None), Decimal(0))
    unknown = sum((decimal(r['reservation']['costUsd']) for r in rows if r.get('usage') is None and 'reservation' in r), Decimal(0))
    exposure = actual + unknown
    require(exposure <= decimal(manifest['maxCostUsd']), 'evaluation_budget', 'Replay exposure exceeds admitted ceiling')
    complete = [r for r in rows if r['status'] == 'completed']
    actual_tokens = sum(r['usage']['tokens'] for r in rows if r.get('usage') is not None)
    unknown_tokens = sum(r['reservation']['tokens'] for r in rows if r.get('usage') is None and 'reservation' in r)
    reserved = sum((decimal(r['reservation']['costUsd']) for r in rows if 'reservation' in r), Decimal(0))
    report = {'schemaVersion': VERSION, 'manifestHash': manifest['manifestHash'],
              'cases': {k: v['status'] for k, v in journal['cases'].items()}, 'plannedCases': 12,
              'completedCases': len(complete), 'matchedCases': sum(r.get('matches', False) for r in complete),
              'reviewedCases': len(reviewed), 'budget': {
                'reserved': {'costUsd': quantity(reserved), 'tokens': sum(r['reservation']['tokens'] for r in rows if 'reservation' in r)},
                'actual': {'costUsd': quantity(actual), 'tokens': actual_tokens},
                'unknown': {'costUsd': quantity(unknown), 'tokens': unknown_tokens},
                'exposure': {'costUsd': quantity(exposure), 'tokens': actual_tokens + unknown_tokens}},
              'attempts': sum('reservation' in r for r in rows), 'retries': 0,
              'diagnosticGate': 'passed' if len(complete) == len(reviewed) == 12
                 and all(r['matches'] for r in complete) and all(reviewed.values()) else 'incomplete'
                 if len(complete) < 12 or len(reviewed) < 12 else 'failed',
              'promotionAuthorized': False, 'scope': manifest['scope'], 'calibrationClaim': False}
    atomic_json(root / 'report.json', report)
    return report


def summarize_evaluation(outputdir):
    with _batch_lock(outputdir) as root:
        manifest, journal = read_json(root / 'preregistration.json'), read_json(root / 'journal.json')
        require(journal['manifestHash'] == manifest['manifestHash'], 'evaluation_evidence', 'Journal binding changed')
        return _summarize(root, manifest, journal)


def run_evaluation(outputdir, policy_factory, pricing_spec, max_usd='1.25', *, evaluation_version=VERSION):
    manifest = preregister(pricing_spec, max_usd=max_usd, evaluation_version=evaluation_version)
    auth = pricing_spec.get('authorization', {})
    require(getattr(policy_factory, 'evaluation_mode', None) == 'external'
            and auth.get('manifestHash') == manifest['manifestHash']
            and auth.get('pricingVerified') is True and auth.get('offlineGatesPassed') is True
            and bool(auth.get('evidenceRefs')), 'evaluation_admission', 'Replay needs manifest-bound offline/pricing admission')
    with _batch_lock(outputdir) as root:
        if (root / 'preregistration.json').exists():
            require(read_json(root / 'preregistration.json') == manifest, 'evaluation_manifest_conflict', 'Replay input changed')
            journal = read_json(root / 'journal.json')
            _validate_journal(manifest, journal)
        else:
            require(all(path.name == '.evaluation.lock' for path in root.iterdir()),
                    'evaluation_evidence', 'Missing preregistration cannot reset existing replay artifacts')
            atomic_json(root / 'preregistration.json', manifest)
            journal = {'manifestHash': manifest['manifestHash'],
                       'cases': {c['evaluationId']: {'status': 'planned'} for c in manifest['cases']}}
            atomic_json(root / 'journal.json', journal)
        for case in manifest['cases']:
            row = journal['cases'][case['evaluationId']]
            if row['status'] != 'planned':
                continue
            try:
                policy = policy_factory(clone(case['spec']))
            except WorldError as error:
                if error.code != 'provider_failure_stop':
                    raise
                for pending in journal['cases'].values():
                    if pending['status'] == 'planned':
                        pending['status'] = 'provider_stopped'
                atomic_json(root / 'journal.json', journal)
                break
            try:
                _bind_external_policy(policy, case['spec'])
                observation, candidate = (case['actorPayload']['observation'], case['actorPayload']['candidateDecision'])
                reservation = policy.reservation(clone(observation), review=clone(candidate))
                exposure = _summarize(root, manifest, journal)['budget']['exposure']['costUsd']
                if decimal(exposure) + decimal(reservation['costUsd']) > decimal(manifest['maxCostUsd']):
                    row.update(status='budget_stopped')
                    atomic_json(root / 'journal.json', journal)
                    continue
                row.update(status='unknown', reservation=reservation, usage=None)
                atomic_json(root / 'journal.json', journal)  # allowance is durable BEFORE dispatch
                usage = None
                shape_error = None
                try:
                    response = policy.decide(clone(observation), review=clone(candidate))
                    usage = response.usage
                    decision = validate_decision(case['spec'], response.decision, observation['actorId'], observation,
                                                 phase=observation['phase'])
                    assessment = validate_assessment(response.assessment, observation, decision, mode=review_mode(case['spec']))
                    status = assessment_status(assessment, mode=review_mode(case['spec']))
                    if status == 'unresolved' and usage is not None:
                        row['withheldReview'] = _withheld_review(manifest, case, decision, assessment)
                    require(status == 'clear', 'consistency_unresolved', 'Revision did not clear its assessment')
                    row.update(status='completed', decision=decision, assessment=assessment,
                               matches=_matches(case, decision))
                except Exception as error:
                    usage = usage if usage is not None else getattr(error, 'usage', None)
                    row.update(status='failed' if usage is not None else 'unknown',
                               errorCode=error.code if isinstance(error, WorldError) else 'policy_decision_failed',
                               errorMessage=_error_message(error))
                    shape_error = error
                if usage is not None:
                    require(type(usage.get('tokens')) is int and 0 <= usage['tokens'] <= reservation['tokens']
                            and Decimal(0) <= decimal(usage['costUsd']) <= decimal(reservation['costUsd']),
                            'reservation_exceeded', 'Replay usage exceeds its reservation')
                    row['usage'] = clone(usage)
                if shape_error is not None:
                    diagnostic = _optional_review_shape(manifest, case, row, shape_error)
                    if diagnostic is not None:
                        row['reviewShape'] = diagnostic
                atomic_json(root / 'journal.json', journal)
            finally:
                policy.close()
        return _summarize(root, manifest, journal)
