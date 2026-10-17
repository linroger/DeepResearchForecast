"""Real causal barriers for optional candidate -> consistency revision."""
from copy import deepcopy
import threading

import pytest

from app.services.world_simulation.contracts import WorldError
from app.services.world_simulation.controller import PolicyResponse, run_round
from app.services.world_simulation.examples import ExamplePolicy, example_spec
from app.services.world_simulation.review import KINDS, MODE, review_mode, validate_assessment
from app.services.world_simulation.store import WorldStore

pytestmark = pytest.mark.guarded_runner


def assessment(obs, decision, status='clear'):
    return {'status': status, 'checks': [
        {'kind': kind, 'objectiveIndices': list(range(len(obs['actor']['objectives']))),
         'intentIndices': list(range(len(decision['intents']))),
         'evidencePaths': [['actor', 'objectives'], ['world']],
         'explanation': 'The final decision is checked against this actor observation.'}
        for kind in sorted(KINDS)]}


def raw(decision):
    value = {k: deepcopy(v) for k, v in decision.items() if k not in {'round', 'phase', 'decisionId'}}
    value['intents'] = [{k: v for k, v in i.items() if k not in {'intentId', 'actorId', 'phase'}}
                        for i in value['intents']]
    return value


def specification(domain='investment'):
    spec = example_spec(domain, periods=1)
    spec['policy'] = {'decisionReview': MODE}
    spec['limits']['maxConcurrentCalls'] = 1
    if domain == 'investment':
        spec['initialState']['metrics']['capacity']['value'] = '3'
        next(a for a in spec['actors'] if a['actorId'] == 'buyer')['objectives'] = ['Buy capacity minus one units.']
    else:
        next(a for a in spec['actors'] if a['actorId'] == 'org_c')['objectives'] = [
            'Wait while coalition_ab is none; oppose only when it is allied.']
    return spec


class RevisingPolicy(ExamplePolicy):
    decision_review = MODE

    def __init__(self, domain):
        super().__init__(domain)
        self.calls = []

    def decide(self, obs, *, review=None):
        self.calls.append((obs['actorId'], obs['phase'], review is not None))
        decision = raw(review) if review is not None else super().decide(obs)
        focal = obs['phase'] == 'proposal' and obs['actorId'] == ('buyer' if self.domain == 'investment' else 'org_c')
        if focal and self.domain == 'investment':
            quantity = '2' if review is not None else '3'
            decision['intents'] = [{'templateId': 'purchase', 'operation': 'propose',
                                    'parameters': {'quantity': quantity, 'price': quantity}}]
            decision['rationale'] = 'Buy two units for two currency.'
        elif focal:
            decision['intents'] = [] if review is not None else [
                {'templateId': 'program_vote', 'operation': 'execute', 'parameters': {'support': False}}]
            decision['rationale'] = 'Wait for the declared coalition trigger.'
            if review is not None:
                decision['status'] = 'wait'
        if review is None:
            return PolicyResponse(decision, {'tokens': 0, 'costUsd': '0'})
        return PolicyResponse(decision, {'tokens': 0, 'costUsd': '0'}, assessment=assessment(obs, decision))


@pytest.mark.parametrize('domain', ['investment', 'coalition'])
def test_causal_loop_uses_revised_choice_before_effects(tmp_path, domain):
    spec = specification(domain)
    policy = RevisingPolicy(domain)
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('test')
        head = run_round(store, policy, fence)
        if domain == 'investment':
            assert head['accounts']['buyer_stock']['balance'] == '2'
        else:
            assert not [r for r in store.rounds()[0]['resolutions'] if r['actorId'] == 'org_c']
        focal = 'buyer' if domain == 'investment' else 'org_c'
        slot = f'1:proposal:{focal}'
        candidate = store.consistency_state(slot)['candidate']
        final = store.decision(slot)
        assert candidate['intents'] != final['intents']
        attempts = [a for a in store.budget_summary()['attempts'] if a['slot'] == slot]
        assert [a['purpose'] for a in attempts] == ['candidate', 'revision']
        assert [a['status'] for a in attempts] == ['succeeded', 'succeeded']
        store.release_writer(fence)
    with WorldStore(tmp_path / 'world.sqlite3', read_only=True) as store:
        assert store.head() == head and store.decision(slot) == final


def test_unresolved_revision_stops_without_committing_or_third_call(tmp_path):
    class Unresolved(RevisingPolicy):
        def decide(self, obs, *, review=None):
            result = super().decide(obs, review=review)
            if review is not None and obs['actorId'] == 'buyer':
                result.assessment['status'] = 'unresolved'
            return result
    policy = Unresolved('investment')
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, specification()) as store:
        fence = store.acquire_writer('first')
        with pytest.raises(WorldError, match='consistency stage'):
            run_round(store, policy, fence)
        assert store.head()['round'] == 0 and store.decision('1:proposal:buyer') is None
        buyer = [a for a in store.budget_summary()['attempts'] if a['slot'] == '1:proposal:buyer']
        assert [a['status'] for a in buyer] == ['succeeded', 'failed']
        assert buyer[-1]['errorCode'] == 'consistency_unresolved'
        store.release_writer(fence)
    before = list(policy.calls)
    with WorldStore(path) as store:
        fence = store.acquire_writer('resume')
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert policy.calls == before and store.head()['round'] == 0


def test_failed_candidate_has_no_unreviewed_replacement(tmp_path):
    class Unavailable(RevisingPolicy):
        def decide(self, obs, *, review=None):
            if obs['actorId'] == 'buyer':
                self.calls.append(('buyer', obs['phase'], False))
                raise RuntimeError('RAW_PROVIDER_BODY_NOT_FOR_LOGGING')
            return super().decide(obs, review=review)
    policy = Unavailable('investment')
    with WorldStore(tmp_path / 'world.sqlite3', specification()) as store:
        fence = store.acquire_writer('test')
        with pytest.raises(WorldError) as error:
            run_round(store, policy, fence)
        assert 'RAW_PROVIDER' not in str(error.value)
        assert [c for c in policy.calls if c[0] == 'buyer'] == [('buyer', 'proposal', False)]
        assert store.head()['round'] == 0
        before = list(policy.calls)
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert policy.calls == before


def test_cancel_after_candidate_resumes_only_revision(tmp_path):
    cancel = threading.Event()
    class CancelAfterCandidate(RevisingPolicy):
        def decide(self, obs, *, review=None):
            result = super().decide(obs, review=review)
            if obs['actorId'] == 'buyer' and review is None:
                cancel.set()
            return result
    policy = CancelAfterCandidate('investment')
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, specification()) as store:
        fence = store.acquire_writer('first')
        with pytest.raises(WorldError):
            run_round(store, policy, fence, cancelled=cancel.is_set)
        assert store.consistency_state('1:proposal:buyer')['candidate'] is not None
        assert store.decision('1:proposal:buyer') is None and store.head()['round'] == 0
        store.release_writer(fence)
    cancel.clear()
    with WorldStore(path) as store:
        fence = store.acquire_writer('resume')
        run_round(store, policy, fence)
        assert store.head()['accounts']['buyer_stock']['balance'] == '2'
    assert [c[2] for c in policy.calls if c[:2] == ('buyer', 'proposal')] == [False, True]


def test_effective_policy_mismatch_rejects_before_any_call(tmp_path):
    policy = RevisingPolicy('investment')
    policy.decision_review = None
    with WorldStore(tmp_path / 'world.sqlite3', specification()) as store:
        fence = store.acquire_writer('test')
        with pytest.raises(WorldError, match='Effective actor review'):
            run_round(store, policy, fence)
        assert not policy.calls and not store.budget_summary()['attempts']


@pytest.mark.parametrize('value', [None, '', 'off', True, [], {}, 'ACTOR-CONSISTENCY-V1'])
def test_invalid_present_review_mode_rejected(value):
    with pytest.raises(WorldError):
        review_mode({'policy': {'decisionReview': value}})


def test_revision_mode_requires_two_calls_but_absence_keeps_legacy():
    assert review_mode({}) is None
    with pytest.raises(WorldError):
        review_mode({'policy': {'decisionReview': MODE}, 'limits': {'maxAttemptsPerSlot': 1}})


@pytest.mark.parametrize('mutation', ['status', 'missing_kind', 'goal_index', 'intent_index', 'hidden_path',
                                    'absent_path', 'negative_index', 'bool_index', 'extra_field'])
def test_assessment_rejects_unbound_or_incomplete_claims(mutation):
    obs = {'actor': {'objectives': ['A goal']}, 'world': {}, 'messages': []}
    decision = {'intents': [{'templateId': 'example'}]}
    value = assessment(obs, decision)
    check = value['checks'][0]
    if mutation == 'status':
        value['status'] = []
    elif mutation == 'missing_kind':
        value['checks'].pop()
    elif mutation == 'goal_index':
        check['objectiveIndices'] = [True]
    elif mutation == 'intent_index':
        check['intentIndices'] = [2]
    elif mutation == 'hidden_path':
        check['evidencePaths'] = [['fullSpec', 'secret']]
    elif mutation == 'absent_path':
        check['evidencePaths'] = [['world', 'secret']]
    elif mutation == 'negative_index':
        check['evidencePaths'] = [['actor', 'objectives', -1]]
    elif mutation == 'bool_index':
        check['evidencePaths'] = [['actor', 'objectives', True]]
    else:
        check['expectedAnswer'] = 'Injected answer'
    with pytest.raises(WorldError):
        validate_assessment(value, obs, decision)


def test_compiler_preserves_pinned_mode_without_implicit_upgrade():
    from test_world_compiler import compile_proposal, proposal
    raw_spec = proposal()
    raw_spec['policy'] = {'decisionReview': MODE}
    spec = compile_proposal(raw_spec)
    assert spec['policy'] == raw_spec['policy']
    old = compile_proposal()
    assert 'policy' not in old and review_mode(old) is None


def test_evaluator_forwards_review_without_relabeling_it_as_retry(tmp_path):
    from app.services.world_simulation.evaluation import _ReservedPolicy, _trace, _operational_report
    policy = RevisingPolicy('investment')
    policy.evaluation_mode = 'scripted'
    wrapped = _ReservedPolicy(policy, specification(), 'scripted')
    with WorldStore(tmp_path / 'world.sqlite3', specification()) as store:
        fence = store.acquire_writer('test')
        run_round(store, wrapped, fence)
        assert all('consistencyReview' in r for r in _trace(store)['records'])
        calls = wrapped.calls
        assert sum(c.get('purpose') == 'candidate' for c in calls) == sum(c.get('purpose') == 'revision' for c in calls)
        budget = store.budget_summary()
        summary = _operational_report([{'evaluationId': 'case'}], {'case': {
            'budget': budget, 'calls': calls, 'operations': {'rejectedCommittedIntents': 0,
            'totalCommittedIntents': 0, 'committedAbstentions': 0}}})
        assert summary['knownRetries'] == 0
