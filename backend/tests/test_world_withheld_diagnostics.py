"""Validated private diagnostics never turn an unresolved response into an action."""
import json

import pytest

from app.services.world_simulation import consistency_evaluation as replay
from app.services.world_simulation.artifacts import atomic_json
from app.services.world_simulation.contracts import WorldError, digest
from test_world_consistency_evaluation import factory_for, pricing

pytestmark = pytest.mark.guarded_runner


def admitted(mode='actor-consistency-v2'):
    config = pricing()
    config['policy']['decisionReview'] = mode
    manifest = replay.preregister(config, '1.25')
    config['authorization'] = {'manifestHash': manifest['manifestHash'], 'offlineGatesPassed': True,
                               'pricingVerified': True, 'evidenceRefs': ['fixture://private-diagnostics']}
    return config, manifest


@pytest.mark.parametrize('mode', ['actor-consistency-v1', 'actor-consistency-v2'])
def test_validated_unresolved_is_retained_privately_but_never_admitted_or_retried(tmp_path, mode):
    config, manifest = admitted(mode)
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure='unresolved')
    root = tmp_path / 'run'
    try:
        report = replay.run_evaluation(root, factory, config)
        case = manifest['cases'][0]
        journal = json.loads((root / 'journal.json').read_text())
        row = journal['cases'][case['evaluationId']]
        assert row['status'] == 'failed' and row['errorCode'] == 'consistency_unresolved'
        retained = row['withheldReview']
        assert set(retained) == {'schemaVersion', 'manifestHash', 'evaluationId', 'observationHash',
                                 'candidateHash', 'decision', 'assessment', 'receiptHash'}
        assert retained['schemaVersion'] == 'world-withheld-review/v1'
        assert retained['manifestHash'] == manifest['manifestHash']
        assert retained['evaluationId'] == case['evaluationId']
        assert retained['observationHash'] == digest(case['actorPayload']['observation'])
        assert retained['candidateHash'] == digest(case['actorPayload']['candidateDecision'])
        assert retained['assessment']['status'] == 'unresolved'
        assert retained['decision']['observationId'] == case['actorPayload']['observation']['observationId']
        assert retained['receiptHash'] == digest({k: v for k, v in retained.items() if k != 'receiptHash'})
        assert 'matches' not in row and 'decision' not in row and 'assessment' not in row
        assert row['usage']['tokens'] == 30 and report['completedCases'] == 11
        assert report['matchedCases'] == 11 and report['diagnosticGate'] == 'incomplete'
        assert 'withheldReview' not in json.dumps(report)
        assert replay.run_evaluation(root, factory, config) == report and len(calls) == 12
        review = {'evaluationId': case['evaluationId'], 'resultHash': digest(row), 'passed': True,
                  'reviewerType': 'independent-agent', 'reviewer': 'fixture', 'note': 'Cannot credit withheld.'}
        atomic_json(root / 'qualitative-review.json', {'manifestHash': manifest['manifestHash'], 'reviews': [review]})
        with pytest.raises(WorldError, match='complete directed result'):
            replay.summarize_evaluation(root)
        (root / 'qualitative-review.json').unlink()
        del row['withheldReview']
        atomic_json(root / 'journal.json', journal)
        assert replay.summarize_evaluation(root) == report  # old failed rows remain readable
        assert len(calls) == 12
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize('defect', ['manifest', 'case', 'observation', 'candidate', 'digest',
                                   'assessment_status', 'decision_binding', 'extra', 'admitted'])
def test_withheld_diagnostic_tamper_rejects_before_summary_or_dispatch(tmp_path, defect):
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure='unresolved')
    root = tmp_path / 'run'
    try:
        replay.run_evaluation(root, factory, config)
        journal = json.loads((root / 'journal.json').read_text())
        row = journal['cases'][manifest['cases'][0]['evaluationId']]
        retained = row['withheldReview']
        fields = {'manifest': 'manifestHash', 'case': 'evaluationId', 'observation': 'observationHash',
                  'candidate': 'candidateHash', 'digest': 'receiptHash'}
        if defect in fields:
            retained[fields[defect]] = 'wrong'
        elif defect == 'assessment_status':
            retained['assessment']['status'] = 'clear'
        elif defect == 'decision_binding':
            retained['decision']['actorId'] = 'foreign_actor'
        elif defect == 'extra':
            retained['providerBody'] = 'SECRET_RAW_ENVELOPE'
        else:
            row['status'] = 'completed'
        if defect != 'digest':
            retained['receiptHash'] = digest({k: v for k, v in retained.items() if k != 'receiptHash'})
        before = (root / 'report.json').read_bytes()
        atomic_json(root / 'journal.json', journal)
        with pytest.raises(WorldError):
            replay.summarize_evaluation(root)
        with pytest.raises(WorldError):
            replay.run_evaluation(root, factory, config)
        assert (root / 'report.json').read_bytes() == before and len(calls) == 12
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize('failure', ['unknown', 'invalid_assessment', 'spoofed_code'])
def test_unvalidated_or_unknown_response_never_creates_withheld_payload(tmp_path, failure):
    from app.services.world_simulation.policy import PolicyFailure

    config, manifest = admitted('actor-consistency-v1')
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure=failure)
    if failure == 'spoofed_code':
        original = factory
        def factory(spec):
            policy = original(spec)
            def fail(*args, **kwargs):
                raise PolicyFailure('consistency_unresolved', 'PRIVATE_EXCEPTION_TEXT',
                                    usage={'tokens': 30, 'costUsd': '0.00014'})
            policy.decide = fail
            return policy
        factory.evaluation_mode = 'external'
    try:
        replay.run_evaluation(tmp_path / 'run', factory, config)
        journal = json.loads((tmp_path / 'run/journal.json').read_text())
        assert all('withheldReview' not in row for row in journal['cases'].values())
        assert 'PRIVATE_EXCEPTION_TEXT' not in json.dumps(journal)
    finally:
        for client in clients:
            client.close()


def test_failed_atomic_diagnostic_write_does_not_renew_request(tmp_path, monkeypatch):
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure='unresolved')
    original = replay.atomic_json
    def fail_retained(path, value):
        if path.name == 'journal.json' and any('withheldReview' in row for row in value['cases'].values()):
            raise OSError('simulated journal replacement failure')
        return original(path, value)
    root = tmp_path / 'run'
    try:
        monkeypatch.setattr(replay, 'atomic_json', fail_retained)
        with pytest.raises(OSError):
            replay.run_evaluation(root, factory, config)
        assert len(calls) == 1
        saved = json.loads((root / 'journal.json').read_text())
        assert saved['cases'][manifest['cases'][0]['evaluationId']]['status'] == 'unknown'
        monkeypatch.setattr(replay, 'atomic_json', original)
        # Refuse further new requests for this recovery check; the consumed row must be skipped.
        def no_dispatch(spec):
            assert spec == manifest['cases'][1]['spec']
            assert spec != manifest['cases'][0]['spec']
            raise RuntimeError('next unconsumed case reached')
        no_dispatch.evaluation_mode = 'external'
        with pytest.raises(RuntimeError, match='next unconsumed'):
            replay.run_evaluation(root, no_dispatch, config)
        assert len(calls) == 1
        assert json.loads((root / 'journal.json').read_text()) == saved
    finally:
        for client in clients:
            client.close()


def test_directed_transport_stop_uses_actual_journal_and_finishes_remaining_rows(tmp_path):
    from test_world_evaluation_launch import load_launcher

    config, manifest = admitted()
    calls = []
    original, clients = factory_for(manifest, calls, first_failure='transport')
    root = tmp_path / 'run'
    launcher = load_launcher()
    def factory(spec):
        if launcher.provider_failure_stop(root):
            raise WorldError('provider_failure_stop', 'Stopped repeated transport failures')
        return original(spec)
    factory.evaluation_mode = 'external'
    try:
        report = replay.run_evaluation(root, factory, config)
        assert len(calls) == report['attempts'] == 3
        assert list(report['cases'].values()).count('unknown') == 3
        assert list(report['cases'].values()).count('provider_stopped') == 9
        assert report['completedCases'] == 0 and report['diagnosticGate'] == 'incomplete'
        journal = json.loads((root / 'journal.json').read_text())
        for row in journal['cases'].values():
            if row['status'] == 'provider_stopped':
                assert row == {'status': 'provider_stopped'}
        assert 'SECRET_PROVIDER_ERROR_BODY' not in json.dumps(journal)
        assert replay.run_evaluation(root, factory, config) == report and len(calls) == 3
    finally:
        for client in clients:
            client.close()
