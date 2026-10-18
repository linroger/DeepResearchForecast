"""Per-check verdicts drive admission without a redundant generated aggregate."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.services.world_simulation.contracts import WorldError
from app.services.world_simulation.review import validate_assessment

pytestmark = pytest.mark.guarded_runner
MODE_V3 = 'actor-consistency-v3'


def checked(verdict='consistent'):
    return {'checks': [{'kind': kind, 'verdict': verdict, 'explanation': 'This check states its own judgment.'}
                       for kind in ('goal_alignment', 'conditional_timing', 'quantity_consistency',
                                    'explanation_consistency')]}


def test_explicit_verdicts_are_valid_without_a_generated_aggregate():
    value = checked()
    assert validate_assessment(value, {}, {}, mode=MODE_V3) == value
    assert 'status' not in value


def test_production_unresolved_reason_is_private_durable_and_its_decision_commits_flagged(tmp_path):
    from app.services.world_simulation.controller import PolicyResponse, run_round
    from app.services.world_simulation.store import WorldStore
    from test_world_consistency_controller import RevisingPolicy, specification

    class Concerned(RevisingPolicy):
        decision_review = MODE_V3
        def decide(self, obs, *, review=None):
            output = super().decide(obs, review=review)
            if review is None:
                return output
            value = checked()
            if obs['actorId'] == 'buyer':
                value['checks'][0].update(verdict='unknown', explanation='PRIVATE_VALIDATED_CONCERN')
            return PolicyResponse(output.decision, output.usage, assessment=value)
    spec = specification()
    spec['policy']['decisionReview'] = MODE_V3
    path = tmp_path / 'world.sqlite3'
    policy = Concerned('investment')
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('writer')
        head = run_round(store, policy, fence)  # An unresolved verdict no longer ends the round.
        entry = store._verified_consistency('1:proposal:buyer')[1][-1]
        assert entry['assessment'] is not None, 'A validated current concern must not be discarded'
        assert entry['status'] == 'failed' and entry['assessment']['checks'][0]['verdict'] == 'unknown'
        assert store.decision('1:proposal:buyer') == {**entry['decision'], 'consistencyStatus': 'unresolved'}
        assert store.consistency_receipt('1:proposal:buyer') is None and head['round'] == 1
        assert 'PRIVATE_VALIDATED_CONCERN' not in json.dumps(store.budget_summary())
        assert 'PRIVATE_VALIDATED_CONCERN' not in json.dumps(store.read_bundle())
        receipt = store.withheld_consistency_receipt('1:proposal:buyer')
        assert receipt['state'] == 'withheld' and 'PRIVATE_VALIDATED_CONCERN' in json.dumps(receipt)
        store.release_writer(fence)
    calls = deepcopy(policy.calls)
    with WorldStore(path, read_only=True) as store:
        assert store.withheld_consistency_receipt('1:proposal:buyer') == receipt
        assert store.head() == head and policy.calls == calls


@pytest.mark.parametrize('verdict,status', [('consistent', 'clear'), ('inconsistent', 'unresolved'),
                                         ('unknown', 'unresolved')])
def test_aggregate_is_derived_from_every_validated_check(verdict, status):
    from app.services.world_simulation.review import assessment_status
    value = checked()
    value['checks'][2]['verdict'] = verdict
    assert assessment_status(value, mode=MODE_V3) == status
    assert validate_assessment(value, {}, {}, mode=MODE_V3) == value


@pytest.mark.parametrize('defect', ['aggregate', 'missing', 'duplicate', 'extra', 'invalid_verdict', 'boolean', 'empty'])
def test_no_missing_malformed_or_extra_check_can_become_clear(defect):
    from app.services.world_simulation.review import assessment_status
    value = checked()
    if defect == 'aggregate':
        value['status'] = 'clear'
    elif defect == 'missing':
        value['checks'].pop()
    elif defect == 'duplicate':
        value['checks'][1]['kind'] = value['checks'][0]['kind']
    elif defect == 'extra':
        value['checks'][0]['status'] = 'clear'
    elif defect == 'invalid_verdict':
        value['checks'][0]['verdict'] = 'probably'
    elif defect == 'boolean':
        value['checks'][0]['verdict'] = True
    else:
        value['checks'] = []
    for operation in (lambda: validate_assessment(value, {}, {}, mode=MODE_V3),
                      lambda: assessment_status(value, mode=MODE_V3)):
        with pytest.raises(WorldError):
            operation()


@pytest.mark.parametrize('verdict', ['consistent', 'inconsistent', 'unknown'])
def test_real_controller_and_reopened_store_use_same_aggregate(tmp_path, verdict):
    from app.services.world_simulation.controller import PolicyResponse, run_round
    from app.services.world_simulation.store import WorldStore
    from test_world_consistency_controller import RevisingPolicy, specification

    class PerCheck(RevisingPolicy):
        decision_review = MODE_V3
        def decide(self, obs, *, review=None):
            output = super().decide(obs, review=review)
            if review is None:
                return output
            result = checked()
            if obs['actorId'] == 'buyer':
                result['checks'][1]['verdict'] = verdict
            return PolicyResponse(output.decision, output.usage, assessment=result)
    spec = specification()
    spec['policy']['decisionReview'] = MODE_V3
    path = tmp_path / 'world.sqlite3'
    policy = PerCheck('investment')
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('first')
        run_round(store, policy, fence)  # A nonclear aggregate commits flagged instead of ending the round.
        assert store.head()['accounts']['buyer_stock']['balance'] == '2'
        committed = store.decision('1:proposal:buyer')
        assert committed.get('consistencyStatus') == (None if verdict == 'consistent' else 'unresolved')
        attempts = [a for a in store.budget_summary()['attempts'] if a['slot'] == '1:proposal:buyer']
        assert len(attempts) == 2
        store.release_writer(fence)
    calls = deepcopy(policy.calls)
    with WorldStore(path, read_only=True) as store:
        assert store.head()['round'] == 1 and store.decision('1:proposal:buyer') == committed
        assert policy.calls == calls


def v3_pricing():
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/release-readiness/check-verdicts/live-policy.json').read_text())


@pytest.mark.parametrize('unresolved', [False, True])
def test_actual_sdk_v3_replay_retains_per_check_evidence_without_extra_dispatch(tmp_path, unresolved):
    from app.services.world_simulation import consistency_evaluation as replay
    from test_world_consistency_evaluation import factory_for

    config = v3_pricing()
    manifest = replay.preregister(config, '1.25')
    config['authorization'] = {'manifestHash': manifest['manifestHash'], 'offlineGatesPassed': True,
                               'pricingVerified': True, 'evidenceRefs': ['fixture://v3-offline']}
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure='unresolved' if unresolved else None)
    root = tmp_path / 'run'
    try:
        report = replay.run_evaluation(root, factory, config)
        assert report['completedCases'] == (11 if unresolved else 12) and len(calls) == 12
        journal = json.loads((root / 'journal.json').read_text())
        row = journal['cases'][manifest['cases'][0]['evaluationId']]
        review = row['withheldReview']['assessment'] if unresolved else row['assessment']
        assert set(review) == {'checks'}
        assert review['checks'][0]['verdict'] == ('unknown' if unresolved else 'consistent')
        assert report['diagnosticGate'] == 'incomplete' and report['promotionAuthorized'] is False
        assert replay.run_evaluation(root, factory, config) == report and len(calls) == 12
        if unresolved:
            from app.services.world_simulation.artifacts import atomic_json
            from app.services.world_simulation.contracts import digest
            retained = row['withheldReview']
            retained['assessment']['checks'][0]['verdict'] = 'consistent'
            retained['receiptHash'] = digest({k: v for k, v in retained.items() if k != 'receiptHash'})
            atomic_json(root / 'journal.json', journal)
            with pytest.raises(WorldError, match='unresolved assessment'):
                replay.summarize_evaluation(root)
            assert len(calls) == 12
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize('verdict', ['unknown', 'inconsistent'])
def test_reopen_rejects_nonclear_final_even_with_recomputed_receipt(tmp_path, verdict):
    import sqlite3
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.controller import PolicyResponse, run_round
    from app.services.world_simulation.store import WorldStore
    from test_world_consistency_controller import RevisingPolicy, specification

    class PerCheck(RevisingPolicy):
        decision_review = MODE_V3
        def decide(self, obs, *, review=None):
            output = super().decide(obs, review=review)
            return output if review is None else PolicyResponse(output.decision, output.usage, assessment=checked())
    spec = specification()
    spec['policy']['decisionReview'] = MODE_V3
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('writer')
        run_round(store, PerCheck('investment'), fence)
        entry = store._verified_consistency('1:proposal:buyer')[1][-1]
        entry['assessment']['checks'][0]['verdict'] = verdict
        changed_hash = store._consistency_hash(entry)
        store.release_writer(fence)
    with sqlite3.connect(path) as corrupt:
        corrupt.execute('UPDATE consistency_journal SET assessment=?,receipt_hash=? WHERE attempt_id=?',
                        (canonical_json(entry['assessment']), changed_hash, entry['attempt_id']))
    with pytest.raises(WorldError, match='Consistency journal validation failed|Final assessment is not clear'):
        WorldStore(path, read_only=True)


@pytest.mark.parametrize('value', ['json_object', None, 'json_schema', True, {'type': 'json_object'}])
def test_compiler_preserves_only_explicit_native_json_pin(value):
    from test_world_compiler import compile_proposal, proposal
    raw = proposal()
    raw['policy'] = {'decisionReview': MODE_V3, 'responseFormat': value}
    if value == 'json_object':
        assert compile_proposal(raw)['policy'] == raw['policy']
    else:
        with pytest.raises(WorldError):
            compile_proposal(raw)


def test_v3_directed_preregistration_and_exact_quotes_without_dispatch():
    import sys
    from decimal import Decimal
    from app.services.world_simulation import consistency_evaluation as replay
    from app.services.world_simulation.artifacts import atomic_json
    from test_world_consistency_evaluation import factory_for

    config = v3_pricing()
    manifest = replay.preregister(config, '1.25')
    calls = []
    factory, clients = factory_for(manifest, calls)
    try:
        quotes = []
        for case in manifest['cases']:
            policy = factory(case['spec'])
            assert policy.decision_review == MODE_V3 and policy._response_format == 'json_object'
            quotes.append(policy.reservation(case['actorPayload']['observation'],
                                             review=case['actorPayload']['candidateDecision']))
            policy.close()
        assert not calls and sum(Decimal(q['costUsd']) for q in quotes) <= Decimal('1.25')
        atomic_json(sys.modules['main_offline_guard'].root / 'reviewed-consistency-preregistration.json', manifest)
    finally:
        for client in clients:
            client.close()


def test_fresh_full_v3_preregistration_pins_complete_matrix_and_request_budget():
    """Prepare the future full study; this check never authorizes dispatch."""
    import sys
    from decimal import Decimal
    import httpx
    from openai import OpenAI
    from app.services.world_simulation import evaluation
    from app.services.world_simulation.artifacts import atomic_json
    from app.services.world_simulation.contracts import initial_snapshot, validate_decision
    from app.services.world_simulation.observations import build_observation
    from app.services.world_simulation.policy import StrictHTTPPolicy
    from app.services.world_simulation.review import CANDIDATE_REPAIR_MODE, candidate_error_context

    config = v3_pricing()
    manifest = evaluation.preregister(config, '18', evaluation_version='m5-behavior/v2')
    assert len(manifest['cases']) == 36 and len({case['pairId'] for case in manifest['cases']}) == 18
    assert manifest['domainThresholdPercent'] == 80 and manifest['maxCostUsd'] == '18'
    assert manifest['comparisonRule'] == 'All 18 preregistered paired contrasts must pass separately.'
    calls = []
    def forbidden(request):
        calls.append(request)
        raise AssertionError('Preregistration must never dispatch')
    http = httpx.Client(transport=httpx.MockTransport(forbidden), trust_env=False)
    sdk = OpenAI(api_key='fixture-only-secret-never-real', base_url=config['policy']['baseUrl'], http_client=http)
    try:
        for case in manifest['cases']:
            spec = case['spec']
            assert spec['policy'] == config['policy'] and spec['policy']['candidateRepair'] == CANDIDATE_REPAIR_MODE
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
        atomic_json(sys.modules['main_offline_guard'].root / 'reviewed-preregistration.json', manifest)
    finally:
        sdk.close()
