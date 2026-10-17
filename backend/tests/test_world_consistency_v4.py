"""V4 consumer and separately pinned configuration preflight; no live calls."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

pytestmark = pytest.mark.guarded_runner


def v4_pricing():
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/release-readiness/check-verdicts/lossless-review-fields/live-policy.json').read_text())


@pytest.mark.parametrize('unresolved', [False, True])
def test_actual_sdk_directed_v4_uses_canonical_fields_and_reopens_without_calls(tmp_path, unresolved):
    from app.services.world_simulation import consistency_evaluation as replay
    from test_world_consistency_evaluation import factory_for

    config = v4_pricing()
    manifest = replay.preregister(config, '1.25')
    config['authorization'] = {'manifestHash': manifest['manifestHash'], 'offlineGatesPassed': True,
                               'pricingVerified': True, 'evidenceRefs': ['fixture://v4-current-gate']}
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure='unresolved' if unresolved else None)
    root = tmp_path / 'run'
    try:
        report = replay.run_evaluation(root, factory, config)
        assert len(calls) == report['attempts'] == 12
        assert report['completedCases'] == (11 if unresolved else 12)
        assert report['reviewedCases'] == 0 and report['diagnosticGate'] == 'incomplete'
        assert report['promotionAuthorized'] is False
        journal = json.loads((root / 'journal.json').read_text())
        row = journal['cases'][manifest['cases'][0]['evaluationId']]
        assessment = row['withheldReview']['assessment'] if unresolved else row['assessment']
        assert all(set(c) == {'kind', 'verdict', 'fields'} and set(c['fields']) == {'explanation'}
                   for c in assessment['checks'])
        assert all(c['fields']['explanation'] for c in assessment['checks'])
        if unresolved:
            assert row['status'] == 'failed' and row['errorCode'] == 'consistency_unresolved'
            assert 'decision' not in row and 'matches' not in row
        prior = deepcopy(calls)
        assert replay.run_evaluation(root, factory, config) == report and calls == prior
        assert json.loads((root / 'journal.json').read_text()) == journal
        for wire in calls:
            body = json.loads(wire)
            assert body['reasoning_effort'] == 'high' and body['max_tokens'] == 8192
    finally:
        for client in clients:
            client.close()


def test_v4_complete_review_evidence_hash_includes_every_retained_member(tmp_path):
    from app.services.world_simulation import consistency_evaluation as replay
    from app.services.world_simulation.contracts import WorldError, digest
    from test_world_consistency_evaluation import factory_for

    config = v4_pricing(); manifest = replay.preregister(config, '1.25')
    config['authorization'] = {'manifestHash': manifest['manifestHash'], 'offlineGatesPassed': True,
                               'pricingVerified': True, 'evidenceRefs': ['fixture://v4-current-gate']}
    calls = []; factory, clients = factory_for(manifest, calls)
    root = tmp_path / 'run'
    try:
        replay.run_evaluation(root, factory, config)
        journal = json.loads((root / 'journal.json').read_text())
        reviews = {'manifestHash': manifest['manifestHash'], 'reviews': [
            {'evaluationId': key, 'resultHash': digest(row), 'passed': True,
             'reviewerType': 'independent-agent', 'reviewer': 'fixture reviewer',
             'note': 'Synthetic binding-only verdict, not a live behavior judgment.'}
            for key, row in journal['cases'].items()]}
        (root / 'qualitative-review.json').write_text(json.dumps(reviews))
        assert replay.summarize_evaluation(root)['diagnosticGate'] == 'passed'
        first = next(iter(journal['cases'].values()))
        first['assessment']['checks'][0]['fields']['additional_claim'] = 'A changed retained assertion.'
        (root / 'journal.json').write_text(json.dumps(journal))
        with pytest.raises(WorldError, match='Review must bind'):
            replay.summarize_evaluation(root)
        assert len(calls) == 12
    finally:
        for client in clients:
            client.close()


def test_v4_high_profile_preregistrations_and_quotes_never_dispatch():
    import sys
    from decimal import Decimal
    import httpx
    from openai import OpenAI
    from app.services.world_simulation import consistency_evaluation as replay, evaluation
    from app.services.world_simulation.artifacts import atomic_json
    from app.services.world_simulation.contracts import initial_snapshot, validate_decision
    from app.services.world_simulation.observations import build_observation
    from app.services.world_simulation.policy import StrictHTTPPolicy
    from app.services.world_simulation.review import MODE_V4, CANDIDATE_REPAIR_MODE, candidate_error_context

    config = v4_pricing()
    assert config['policy']['decisionReview'] == MODE_V4
    assert config['policy']['candidateRepair'] == CANDIDATE_REPAIR_MODE
    assert config['policy']['reasoningEffort'] == 'high' and config['maxOutputTokens'] == 8192
    directed = replay.preregister(config, '1.25')
    full = evaluation.preregister(config, '18', evaluation_version='m5-behavior/v2')
    assert len(directed['cases']) == 12 and len(full['cases']) == 36
    assert len({c['pairId'] for c in full['cases']}) == 18 and full['domainThresholdPercent'] == 80
    assert full['comparisonRule'] == 'All 18 preregistered paired contrasts must pass separately.'
    calls = []
    def forbidden(request):
        calls.append(request)
        raise AssertionError('Offline profile verification must not dispatch')
    http = httpx.Client(transport=httpx.MockTransport(forbidden), trust_env=False)
    sdk = OpenAI(api_key='fixture-not-a-secret', base_url=config['policy']['baseUrl'], http_client=http)
    quotes = []
    try:
        for case in directed['cases']:
            policy = StrictHTTPPolicy(case['spec'], client=sdk)
            try:
                evaluation._bind_external_policy(policy, case['spec'])
                quotes.append(policy.reservation(case['actorPayload']['observation'],
                                                review=case['actorPayload']['candidateDecision']))
            finally:
                policy.close()
        assert sum(Decimal(q['costUsd']) for q in quotes) <= Decimal('1.25')
        for case in full['cases']:
            spec = case['spec']; assert spec['policy'] == config['policy']
            policy = StrictHTTPPolicy(spec, client=sdk)
            try:
                evaluation._bind_external_policy(policy, spec)
                for actor in spec['actors']:
                    obs = build_observation(spec, initial_snapshot(spec), actor['actorId'], 1)
                    draft = validate_decision(spec, {'actorId': obs['actorId'], 'observationId': obs['observationId'],
                        'intents': [], 'status': 'wait'}, actor['actorId'], obs, phase='proposal')
                    for review in (None, draft, candidate_error_context(obs, 'invalid_input')):
                        quote = policy.reservation(obs, review=review)
                        assert quote['tokens'] <= spec['limits']['maxTokens']
                        assert Decimal(quote['costUsd']) <= Decimal(spec['limits']['maxCostUsd'])
            finally:
                policy.close()
        assert not calls
        evidence = sys.modules['main_offline_guard'].root
        atomic_json(evidence / 'reviewed-consistency-preregistration.json', directed)
        atomic_json(evidence / 'reviewed-preregistration.json', full)
        atomic_json(evidence / 'v4-profile-quotes.json', {'directedQuotes': quotes,
                    'directedMaximumUsd': str(sum(Decimal(q['costUsd']) for q in quotes)),
                    'fullCaseOpeningRequestsFit': True, 'completeTrajectoryCostGuaranteed': False,
                    'providerCalls': 0, 'profile': config})
    finally:
        sdk.close()


def test_v4_known_validator_failure_keeps_specific_safe_reason_and_charge(tmp_path):
    from app.services.world_simulation import consistency_evaluation as replay
    from test_world_consistency_evaluation import factory_for

    config = v4_pricing(); manifest = replay.preregister(config, '1.25')
    config['authorization'] = {'manifestHash': manifest['manifestHash'], 'offlineGatesPassed': True,
                               'pricingVerified': True, 'evidenceRefs': ['fixture://v4-safe-failure']}
    calls = []; factory, clients = factory_for(manifest, calls, first_failure='invalid_assessment')
    root = tmp_path / 'run'
    try:
        report = replay.run_evaluation(root, factory, config)
        row = json.loads((root / 'journal.json').read_text())['cases'][manifest['cases'][0]['evaluationId']]
        assert row['status'] == 'failed' and row['errorCode'] == 'invalid_assessment'
        assert row['usage']['tokens'] == 30 and report['attempts'] == len(calls) == 12
        assert row['errorMessage'] == 'V4 private fields cannot contain reserved control names'
        assert 'SENTINEL_PROVIDER_BODY' not in json.dumps(row) and 'reviewShape' not in row
        assert report['completedCases'] == 11 and report['diagnosticGate'] == 'incomplete'
    finally:
        for client in clients:
            client.close()
