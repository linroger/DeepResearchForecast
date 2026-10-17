"""Known candidate-output repair preserves the two-call durable boundary."""
from copy import deepcopy
import threading

import pytest

from app.services.world_simulation.contracts import WorldError
from app.services.world_simulation.controller import PolicyResponse, run_round
from app.services.world_simulation.review import (
    CANDIDATE_REPAIR_MODE, MODE_V3, candidate_error_context, validate_candidate_error_context,
)
from app.services.world_simulation.store import WorldStore
from test_world_consistency_controller import RevisingPolicy, specification
from test_world_consistency_v3 import checked

pytestmark = pytest.mark.guarded_runner
SLOT = '1:proposal:buyer'


def repair_spec():
    spec = specification()
    spec['policy'].update(decisionReview=MODE_V3, candidateRepair=CANDIDATE_REPAIR_MODE)
    return spec


class RepairingPolicy(RevisingPolicy):
    decision_review = MODE_V3
    candidate_repair = CANDIDATE_REPAIR_MODE
    evaluation_mode = 'scripted'

    def __init__(self, *, failure='invalid_output', stop=None, revision='clear'):
        super().__init__('investment')
        self.failure, self.stop, self.revision = failure, stop, revision
        self.inputs = []

    def decide(self, obs, *, review=None):
        self.inputs.append(deepcopy(review))
        if obs['actorId'] == 'buyer' and review is None:
            self.calls.append(('buyer', obs['phase'], False))
            if self.stop:
                self.stop.set()
            if self.failure == 'invalid_output':
                return PolicyResponse({'actorId': obs['actorId'], 'observationId': obs['observationId'],
                                       'intents': [], 'unsupported': 'RAW_UNUSABLE_BODY'},
                                      {'tokens': 0, 'costUsd': '0'})
            if self.failure == 'identity':
                return PolicyResponse({'actorId': 'foreign', 'observationId': obs['observationId'], 'intents': []},
                                      {'tokens': 0, 'costUsd': '0'})
            if self.failure == 'generic':
                raise RuntimeError('RAW_UNUSABLE_BODY')
            from app.services.world_simulation.policy import PolicyFailure
            raise PolicyFailure('invalid_decision', 'RAW_UNUSABLE_BODY',
                                usage=None if self.failure == 'unknown' else {'tokens': 0, 'costUsd': '0'})
        if isinstance(review, dict) and review.get('schemaVersion') == 'actor-candidate-error/v1':
            assert review == candidate_error_context(obs, 'invalid_decision')
            self.calls.append((obs['actorId'], obs['phase'], True))
            value = {'actorId': obs['actorId'], 'observationId': obs['observationId'], 'intents': [
                {'templateId': 'purchase', 'operation': 'propose', 'parameters': {'quantity': '2', 'price': '2'}}]}
            if self.revision == 'invalid':
                value['unsupported'] = True
            return PolicyResponse(value, {'tokens': 0, 'costUsd': '0'},
                                  assessment=checked('unknown' if self.revision == 'unknown' else 'consistent'))
        result = super().decide(obs, review=review)
        return PolicyResponse(result.decision, result.usage, assessment=checked() if review is not None else None)


@pytest.mark.parametrize('field', ['actorId', 'observationId'])
def test_error_context_labels_and_binds_actual_identity(field):
    obs = {'actorId': 'buyer', 'observationId': 'observation_1'}
    ctx = candidate_error_context(obs, 'invalid_decision')
    assert validate_candidate_error_context(ctx, obs) == ctx
    bad = {**obs, field: None}
    with pytest.raises(WorldError, match=field):
        candidate_error_context(bad, 'invalid_decision')
    with pytest.raises(WorldError):
        validate_candidate_error_context({**ctx, field: 'foreign'}, obs)


def test_known_local_validation_failure_uses_unused_review_and_separates_reporting(tmp_path):
    from app.services.world_simulation.evaluation import _ReservedPolicy, _operational_report
    spec = repair_spec()
    policy = RepairingPolicy()
    wrapped = _ReservedPolicy(policy, spec, 'scripted')
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('first')
        head = run_round(store, wrapped, fence)
        assert head['accounts']['buyer_stock']['balance'] == '2'
        receipt = store.consistency_receipt(SLOT)
        assert receipt['reviewInputKind'] == 'candidate_error'
        assert receipt['reviewInput']['errorCode'] == 'invalid_decision'
        budget = store.budget_summary()
        attempts = [a for a in budget['attempts'] if a['slot'] == SLOT]
        assert [a['status'] for a in attempts] == ['failed', 'succeeded']
        assert attempts[1]['reviewInputKind'] == 'candidate_error'
        summary = _operational_report([{'evaluationId': 'one'}], {'one': {
            'budget': budget, 'calls': wrapped.calls,
            'operations': {'rejectedCommittedIntents': 0, 'totalCommittedIntents': 0, 'committedAbstentions': 0}}})
        assert summary['candidateRepairCalls'] == 1 and summary['failedGenerationAttempts'] == 1
        assert summary['candidateRevisionCalls'] >= 1 and summary['knownRetries'] == 0
        assert 'RAW_UNUSABLE_BODY' not in str(receipt)
        store.release_writer(fence)
    prior = deepcopy(policy.calls)
    with WorldStore(path) as store:
        assert store.consistency_receipt(SLOT) == receipt
        with pytest.raises(WorldError):
            store.acquire_writer('complete')
    assert policy.calls == prior


def test_durable_failed_candidate_resumes_only_unused_revision(tmp_path):
    stop = threading.Event()
    policy = RepairingPolicy(stop=stop)
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, repair_spec()) as store:
        fence = store.acquire_writer('first')
        with pytest.raises(WorldError):
            run_round(store, policy, fence, cancelled=stop.is_set)
        assert store.consistency_review_input(SLOT)['schemaVersion'] == 'actor-candidate-error/v1'
        assert store.consistency_state(SLOT)['reviewAttempt'] is None
        store.release_writer(fence)
    stop.clear()
    with WorldStore(path) as store:
        fence = store.acquire_writer('resume')
        run_round(store, policy, fence)
        assert store.head()['accounts']['buyer_stock']['balance'] == '2'
    assert [c[2] for c in policy.calls if c[:2] == ('buyer', 'proposal')] == [False, True]


@pytest.mark.parametrize('failure', ['spoofed', 'unknown', 'identity', 'generic'])
def test_non_output_or_unknown_failures_never_gain_repair(tmp_path, failure):
    policy = RepairingPolicy(failure=failure)
    with WorldStore(tmp_path / 'world.sqlite3', repair_spec()) as store:
        fence = store.acquire_writer('first')
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert store.consistency_review_input(SLOT) is None
        prior = deepcopy(policy.calls)
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert policy.calls == prior and store.decision(SLOT) is None
        assert [c[2] for c in policy.calls if c[:2] == ('buyer', 'proposal')] == [False]


@pytest.mark.parametrize('revision', ['invalid', 'unknown'])
def test_failed_revision_never_opens_a_third_call(tmp_path, revision):
    policy = RepairingPolicy(revision=revision)
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, repair_spec()) as store:
        fence = store.acquire_writer('first')
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert [c[2] for c in policy.calls if c[:2] == ('buyer', 'proposal')] == [False, True]
        assert store.decision(SLOT) is None and store.head()['round'] == 0
        assert (store.withheld_consistency_receipt(SLOT) is not None) == (revision == 'unknown')
        store.release_writer(fence)
    before = deepcopy(policy.calls)
    with WorldStore(path) as store:
        fence = store.acquire_writer('resume')
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert policy.calls == before


def test_absent_pin_keeps_v3_candidate_failure_terminal(tmp_path):
    spec = repair_spec()
    del spec['policy']['candidateRepair']
    policy = RepairingPolicy()
    policy.candidate_repair = None
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('first')
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert [c[2] for c in policy.calls if c[:2] == ('buyer', 'proposal')] == [False]


def test_effective_pin_mismatch_rejected_before_any_dispatch(tmp_path):
    policy = RepairingPolicy()
    policy.candidate_repair = None
    with WorldStore(tmp_path / 'world.sqlite3', repair_spec()) as store:
        fence = store.acquire_writer('first')
        with pytest.raises(WorldError, match='repair'):
            run_round(store, policy, fence)
        assert not policy.calls and not store.budget_summary()['attempts']


@pytest.mark.parametrize('failure_at', ['finish', 'review_input'])
def test_persistence_or_integrity_failure_does_not_dispatch_repair(tmp_path, monkeypatch, failure_at):
    policy = RepairingPolicy()
    with WorldStore(tmp_path / 'world.sqlite3', repair_spec()) as store:
        fence = store.acquire_writer('first')
        original = store.finish_consistency_attempt
        if failure_at == 'finish':
            def fail_finish(*args, **kwargs):
                if kwargs.get('repair_eligible'):
                    raise WorldError('invalid_decision', 'Persistence failed with a misleading output code')
                return original(*args, **kwargs)
            monkeypatch.setattr(store, 'finish_consistency_attempt', fail_finish)
        else:
            original_input = store.consistency_review_input
            def fail_input(slot):
                value = original_input(slot)
                if value is not None and slot == SLOT:
                    raise WorldError('invalid_decision', 'Stored review input failed integrity')
                return value
            monkeypatch.setattr(store, 'consistency_review_input', fail_input)
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert [c[2] for c in policy.calls if c[:2] == ('buyer', 'proposal')] == [False]
        assert store.decision(SLOT) is None and store.head()['round'] == 0


import test_world_policy as sdk_fixtures
actor_case = sdk_fixtures.actor_case
boundary = sdk_fixtures.boundary


@pytest.mark.parametrize('defect', ['json', 'grammar'])
def test_real_sdk_candidate_failure_is_metered_repaired_and_durable(tmp_path, actor_case, boundary, defect):
    import json
    from decimal import Decimal
    from app.services.world_simulation.examples import ExamplePolicy
    from app.services.world_simulation.evaluation import _ReservedPolicy

    spec = repair_spec()
    spec['policy'] = {**deepcopy(actor_case.spec['policy']), **spec['policy']}
    spec['limits'].update(maxOutputTokens=512, maxTokens=500000, maxCostUsd='25')
    scripted = ExamplePolicy('investment')
    counts, wires = {}, []
    def response(request, _):
        messages = json.loads(request.content)['messages']
        obs = json.loads(messages[1]['content'])
        key = f"{obs['round']}:{obs['phase']}:{obs['actorId']}"
        counts[key] = counts.get(key, 0) + 1
        wires.append((key, messages))
        decision = scripted.decide(obs)
        if key == SLOT and counts[key] == 1:
            if defect == 'json':
                return 'RAW_UNUSABLE_BODY not JSON'
            decision['intents'] = [{'templateId': 'purchase', 'operation': 'propose',
                                    'parameters': {'quantity': '999999', 'price': '999999'}}]
            decision['rationale'] = 'RAW_UNUSABLE_BODY'
        elif key == SLOT:
            decision['intents'] = [{'templateId': 'purchase', 'operation': 'propose',
                                    'parameters': {'quantity': '2', 'price': '2'}}]
        return json.dumps({'decision': decision, 'assessment': checked()} if counts[key] == 2 else decision)
    case = boundary(spec=spec, content_factory=response)
    wrapped = _ReservedPolicy(case.policy, spec, 'external')
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('first')
        run_round(store, wrapped, fence)
        assert counts[SLOT] == 2 and store.head()['accounts']['buyer_stock']['balance'] == '2'
        receipt = store.consistency_receipt(SLOT)
        assert receipt['reviewInputKind'] == 'candidate_error'
        assert receipt['candidate'] is None and receipt['candidateHash'] is None
        assert [s['status'] for s in receipt['stages']] == ['failed', 'succeeded']
        assert all(s['usage']['tokens'] == 140 for s in receipt['stages'])
        assert Decimal(store.budget_summary()['actual']['costUsd']) == Decimal('0.00056') * len(case.sent)
        assert 'RAW_UNUSABLE_BODY' not in json.dumps([m for key, m in wires if key == SLOT][1])
        store.release_writer(fence)
    before = len(case.sent)
    with WorldStore(path) as store:
        assert store.consistency_receipt(SLOT) == receipt
        with pytest.raises(WorldError):
            store.acquire_writer('completed')
    assert len(case.sent) == before


@pytest.mark.parametrize('tamper', ['missing_decision', 'missing_assessment', 'clear', 'error_code', 'unknown_charge'])
def test_withheld_review_tampering_rejects_even_with_recomputed_receipt(tmp_path, tamper):
    import json
    import sqlite3
    from app.services.world_simulation.contracts import canonical_json
    policy = RepairingPolicy(revision='unknown')
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, repair_spec()) as store:
        fence = store.acquire_writer('first')
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        entry = store._verified_consistency(SLOT)[1][-1]
        assert entry['assessment'] is not None
        if tamper == 'missing_decision':
            entry['decision'] = None
        elif tamper == 'missing_assessment':
            entry['assessment'] = None
        elif tamper == 'clear':
            entry['assessment'] = checked()
        elif tamper == 'error_code':
            entry['error']['code'] = 'invalid_decision'
        else:
            entry['status'] = 'unknown'
        receipt_hash = store._consistency_hash(entry)
        store.release_writer(fence)
    with sqlite3.connect(path) as corrupt:
        corrupt.execute('UPDATE consistency_journal SET decision=?,assessment=?,error=?,receipt_hash=? WHERE attempt_id=?',
                        (None if entry['decision'] is None else canonical_json(entry['decision']),
                         None if entry['assessment'] is None else canonical_json(entry['assessment']),
                         json.dumps(entry['error']), receipt_hash, entry['attempt_id']))
        corrupt.execute('UPDATE attempts SET status=? WHERE attempt_id=?', (entry['status'], entry['attempt_id']))
    with pytest.raises(WorldError):
        WorldStore(path, read_only=True)
