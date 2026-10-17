"""Actual SDK, fixed historical inputs, durable one-call replay diagnostics."""
import json
from pathlib import Path
import sys

import pytest

from app.services.world_simulation import consistency_evaluation as replay
from app.services.world_simulation.artifacts import atomic_json
from app.services.world_simulation.contracts import WorldError, clone, digest
from app.services.world_simulation.policy import StrictHTTPPolicy
from test_world_consistency_controller import assessment, raw

pytestmark = pytest.mark.guarded_runner


def pricing():
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/live-policy.json').read_text())


def admitted(maximum='1.25'):
    config = pricing()
    manifest = replay.preregister(config, maximum)
    config['authorization'] = {'manifestHash': manifest['manifestHash'], 'offlineGatesPassed': True,
                               'pricingVerified': True, 'evidenceRefs': ['fixture://offline-synthetic']}
    return config, manifest


def factory_for(manifest, calls, *, first_failure=None):
    import httpx
    from openai import OpenAI
    clients = []

    def handler(request):
        case = manifest['cases'][len(calls) % len(manifest['cases'])]
        calls.append(request.content)
        body = json.loads(request.content)
        obs = json.loads(body['messages'][1]['content'])
        assert obs == case['actorPayload']['observation']
        assert case['caseId'] not in body['messages'][0]['content']
        assert 'analystOnly' not in request.content.decode()
        if first_failure == 'transport':
            return httpx.Response(429, text='SECRET_PROVIDER_ERROR_BODY')
        if len(calls) == 1 and first_failure == 'unknown':
            raise httpx.ReadTimeout('SENTINEL_PROVIDER_BODY', request=request)
        decision = raw(case['actorPayload']['candidateDecision'])
        if case['caseId'] == 'investment-rationale-action-disagreement':
            decision['intents'][0]['parameters'] = {'quantity': '2', 'price': '2'}
        elif case['caseId'] == 'coalition-opposition-before-trigger':
            decision['intents'] = []
            decision['status'] = 'wait'
            decision['rationale'] = 'The visible conditional trigger has not occurred.'
        review = assessment(obs, decision)
        if manifest['pricing']['policy'].get('decisionReview') == 'actor-consistency-v2':
            review['checks'] = [{'kind': c['kind'], 'explanation': c['explanation']} for c in review['checks']]
        elif manifest['pricing']['policy'].get('decisionReview') in {'actor-consistency-v3', 'actor-consistency-v4'}:
            review = {'checks': [{'kind': c['kind'], 'verdict': 'consistent', 'explanation': c['explanation']}
                                 for c in review['checks']]}
        if len(calls) == 1 and first_failure == 'unresolved':
            if manifest['pricing']['policy'].get('decisionReview') in {'actor-consistency-v3', 'actor-consistency-v4'}:
                review['checks'][0]['verdict'] = 'unknown'
            else:
                review['status'] = 'unresolved'
        if len(calls) == 1 and first_failure == 'invalid_assessment':
            if manifest['pricing']['policy'].get('decisionReview') == 'actor-consistency-v4':
                review['checks'][0]['status'] = 'clear'  # reserved alternate control
            else:
                review['checks'][0]['evidencePaths'] = [['world', 'NO_SUCH_FIELD']]
            review['checks'][0]['explanation'] = 'SENTINEL_PROVIDER_BODY'
        return httpx.Response(200, json={'id': 'fixture', 'object': 'chat.completion', 'created': 1,
            'model': manifest['pricing']['policy']['model'],
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant',
                'content': json.dumps({'decision': decision, 'assessment': review})}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}})

    def factory(spec):
        client = OpenAI(api_key='fixture-not-a-secret', base_url=spec['policy']['baseUrl'], max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        clients.append(client)
        return StrictHTTPPolicy(spec, client=client)
    factory.evaluation_mode = 'external'
    return factory, clients


def test_directed_replay_all_saved_inputs_metered_once_and_reviewed(tmp_path):
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls)
    try:
        report = replay.run_evaluation(tmp_path / 'run', factory, config)
        assert len(calls) == 12 and report['completedCases'] == report['matchedCases'] == 12
        assert report['diagnosticGate'] == 'incomplete' and report['promotionAuthorized'] is False
        journal = json.loads((tmp_path / 'run/journal.json').read_text())
        reviews = [{'evaluationId': key, 'resultHash': digest(row), 'passed': True,
                    'reviewerType': 'independent-agent', 'reviewer': 'synthetic-test-reviewer', 'note': 'Fixture only.'}
                   for key, row in journal['cases'].items()]
        atomic_json(tmp_path / 'run/qualitative-review.json', {'manifestHash': manifest['manifestHash'], 'reviews': reviews})
        final = replay.summarize_evaluation(tmp_path / 'run')
        assert final['diagnosticGate'] == 'passed' and final['reviewedCases'] == 12
        assert final['budget']['unknown']['costUsd'] == '0'
        again = replay.run_evaluation(tmp_path / 'run', factory, config)
        assert again == final and len(calls) == 12
        journal['cases'].pop(next(iter(journal['cases'])))
        atomic_json(tmp_path / 'run/journal.json', journal)
        with pytest.raises(WorldError):
            replay.run_evaluation(tmp_path / 'run', factory, config)
        assert len(calls) == 12
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize('failure', ['unknown', 'unresolved', 'invalid_assessment'])
def test_failed_replay_keeps_exposure_and_never_retries(tmp_path, failure):
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure=failure)
    try:
        report = replay.run_evaluation(tmp_path / 'run', factory, config)
        assert len(calls) == 12 and report['completedCases'] == 11
        assert report['retries'] == 0
        journal = json.loads((tmp_path / 'run/journal.json').read_text())
        row = journal['cases'][manifest['cases'][0]['evaluationId']]
        assert row['status'] == ('unknown' if failure == 'unknown' else 'failed')
        assert row['usage'] is None if failure == 'unknown' else row['usage']['tokens'] == 30
        assert 'SENTINEL_PROVIDER_BODY' not in json.dumps(journal)
        expected = {'invalid_assessment': 'Assessment evidence path is unavailable',
                    'unknown': 'Actor HTTP dispatch timed out; exposure is unknown',
                    'unresolved': replay._GENERIC_FAILURE}
        assert row['errorMessage'] == expected[failure]
        replay.run_evaluation(tmp_path / 'run', factory, config)
        assert len(calls) == 12
    finally:
        for client in clients:
            client.close()


def test_replay_budget_denies_before_first_dispatch(tmp_path):
    config, manifest = admitted('0.000000001')
    calls = []
    factory, clients = factory_for(manifest, calls)
    try:
        report = replay.run_evaluation(tmp_path / 'run', factory, config, max_usd='0.000000001')
        assert not calls and report['budget']['exposure']['costUsd'] == '0'
        assert set(report['cases'].values()) == {'budget_stopped'}
    finally:
        for client in clients:
            client.close()


def test_preregister_and_bound_all_revision_inputs_without_dispatch():
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls)
    reservations = []
    try:
        for case in manifest['cases']:
            policy = factory(clone(case['spec']))
            reservations.append(policy.reservation(case['actorPayload']['observation'],
                                                   review=case['actorPayload']['candidateDecision']))
            policy.close()
        assert not calls and len(reservations) == 12
        from decimal import Decimal
        assert sum(Decimal(r['costUsd']) for r in reservations) <= Decimal(manifest['maxCostUsd'])
        evidence = sys.modules['main_offline_guard'].root
        atomic_json(evidence / 'reviewed-consistency-preregistration.json', manifest)
    finally:
        for client in clients:
            client.close()


def test_missing_preregistration_never_resets_consumed_replay(tmp_path):
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls)
    root = tmp_path / 'run'
    try:
        replay.run_evaluation(root, factory, config)
        assert len(calls) == 12
        before = (root / 'journal.json').read_bytes()
        (root / 'preregistration.json').unlink()
        with pytest.raises(WorldError):
            replay.run_evaluation(root, factory, config)
        assert len(calls) == 12 and (root / 'journal.json').read_bytes() == before
        assert not (root / 'preregistration.json').exists()
    finally:
        for client in clients:
            client.close()


def test_summary_rejects_changed_manifest_under_old_identity(tmp_path):
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls)
    root = tmp_path / 'run'
    try:
        replay.run_evaluation(root, factory, config)
        before = (root / 'report.json').read_bytes()
        changed = json.loads((root / 'preregistration.json').read_text())
        changed['cases'][0]['actorPayload']['candidateDecision']['rationale'] += ' ALTERED AFTER DISPATCH'
        atomic_json(root / 'preregistration.json', changed)
        with pytest.raises(WorldError):
            replay.summarize_evaluation(root)
        assert len(calls) == 12 and (root / 'report.json').read_bytes() == before
    finally:
        for client in clients:
            client.close()


def test_directed_manifest_satisfies_actual_shared_launcher_records(tmp_path):
    from test_world_evaluation_launch import load_launcher
    config, manifest = admitted()
    assert manifest['allocatedUsd'] == manifest['maxCostUsd'] == '1.25'
    launch = load_launcher()
    selected = {'destination': str(tmp_path / 'new-run'), 'maximum': '1.25', 'version': replay.VERSION}
    location, binding = launch.build_phase_records(manifest, selected, config, tmp_path / 'offline')
    launch.persist_phase_records(tmp_path / 'records', location, binding)
    saved = json.loads((tmp_path / 'records/live-launch-binding.json').read_text())
    assert saved['manifestHash'] == manifest['manifestHash'] and saved['allocatedUsd'] == '1.25'
    assert saved['authorization'] == config['authorization']
    assert not (tmp_path / 'new-run').exists()


def test_diagnostic_cannot_echo_arbitrary_world_error_text():
    error = WorldError('invalid_assessment', 'SECRET_PROVIDER_BODY')
    assert replay._error_message(error) == replay._GENERIC_FAILURE
    assert replay._error_message(ValueError('SECRET_PROVIDER_BODY')) == replay._GENERIC_FAILURE
