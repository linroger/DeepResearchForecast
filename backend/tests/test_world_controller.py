"""Cross-domain feedback and persistence through the production round controller."""
import threading

import pytest

from app.services.world_simulation.contracts import WorldError, canonical_json, clone, initial_snapshot
from app.services.world_simulation.controller import run_round, run_to_horizon
from app.services.world_simulation.examples import ExamplePolicy, example_spec
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.store import WorldStore

pytestmark = pytest.mark.guarded_runner


@pytest.mark.parametrize('domain', ['investment', 'trade', 'coalition'])
def test_real_controller_cross_domain_feedback(tmp_path, domain):
    spec = example_spec(domain)
    policy = ExamplePolicy(domain)
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('test')
        final = run_to_horizon(store, policy, fence)
        assert final['round'] == 4
        assert len(store.history()) == 5
        assert all(record['reserved'] == '0' for record in final['accounts'].values())
        if domain == 'investment':
            assert final['metrics']['capacity']['value'] == '7'
            buyer = [o for o in policy.observations if o['actorId'] == 'buyer' and o['phase'] == 'proposal']
            assert [o['world']['metrics']['capacity']['value'] for o in buyer] == ['4', '4', '7', '7']
            assert final['accounts']['capex_sink']['balance'] == '6'
            assert final['accounts']['buyer_stock']['balance'] == '18'
        elif domain == 'trade':
            assert final['rules']['route_a_eligible']['value'] is False
            importer = [o for o in policy.observations if o['actorId'] == 'importer' and o['phase'] == 'proposal']
            assert [o['world']['rules']['route_a_eligible']['value'] for o in importer] == [True, True, False, False]
            assert final['accounts']['supplier_a_cash']['balance'] == '4'
            assert final['accounts']['supplier_b_cash']['balance'] == '6'
        else:
            assert final['relations']['coalition_ab']['value'] == 'allied'
            assert final['rules']['program_authorized']['value'] is True
            assert final['accounts']['institution_budget']['balance'] == '20'
            assert final['accounts']['program_sink']['balance'] == '60'


def test_hidden_world_changes_do_not_change_actual_actor_observation():
    spec = example_spec()
    before = initial_snapshot(spec)
    modified = clone(before)
    modified['accounts']['producer_cash']['balance'] = '999'
    modified['actorStates']['producer']['beliefs'] = ['PRIVATE_SENTINEL']
    spec2 = clone(spec)
    spec2['actors'][0]['objectives'] = ['PRIVATE_OBJECTIVE']
    spec2['actionCatalog'][0]['parameters']['cost'] = '100'
    a = build_observation(spec, before, 'buyer', 1)
    b = build_observation(spec2, modified, 'buyer', 1)
    assert canonical_json(a) == canonical_json(b)
    assert 'PRIVATE' not in canonical_json(a)
    assert 'specHash' not in canonical_json(a)
    assert 'parameters' not in canonical_json(a['options'])


def test_failed_required_slot_never_advances_and_resume_reuses_peer_receipts(tmp_path):
    spec = example_spec(periods=1)
    class FailingPolicy(ExamplePolicy):
        def decide(self, observation):
            if observation['actorId'] == 'buyer':
                raise ValueError('synthetic provider failure')
            return super().decide(observation)
    policy = FailingPolicy('investment')
    path = tmp_path / 'world.sqlite3'
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('first')
        initial = store.head()
        with pytest.raises(WorldError):
            run_round(store, policy, fence)
        assert store.head() == initial
        assert store.decision('1:proposal:producer') is not None
        store.release_writer(fence)
    replay = ExamplePolicy('investment')
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('second')
        with pytest.raises(WorldError):
            run_round(store, replay, fence)
        assert replay.observations == []  # ordinary resume restores no exhausted allowance
        assert store.head() == initial


def test_cancel_before_commit_preserves_head_and_successful_receipts(tmp_path):
    spec = example_spec(periods=1)
    cancel = threading.Event()
    class CancellingPolicy(ExamplePolicy):
        def decide(self, observation):
            result = super().decide(observation)
            cancel.set()
            return result
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('cancel')
        with pytest.raises(WorldError):
            run_round(store, CancellingPolicy('investment'), fence, cancelled=cancel.is_set)
        assert store.head()['round'] == 0


def test_boundary_resume_matches_uninterrupted_semantic_revision(tmp_path):
    spec = example_spec()
    with WorldStore(tmp_path / 'full.sqlite3', spec) as full:
        full_fence = full.acquire_writer('full')
        expected = run_to_horizon(full, ExamplePolicy('investment'), full_fence)
    path = tmp_path / 'resumed.sqlite3'
    with WorldStore(path, spec) as first:
        fence = first.acquire_writer('first')
        run_round(first, ExamplePolicy('investment'), fence)
        first.release_writer(fence)
    with WorldStore(path, spec) as second:
        fence = second.acquire_writer('second')
        result = run_to_horizon(second, ExamplePolicy('investment'), fence)
        assert result == expected


def test_cancel_after_successful_last_attempt_keeps_receipt_for_resume(tmp_path):
    spec = example_spec(periods=1)
    cancel = threading.Event()
    class LastAttemptPolicy(ExamplePolicy):
        attempts = 0
        def decide(self, observation):
            if observation['actorId'] == 'producer' and observation['phase'] == 'proposal':
                self.attempts += 1
                if self.attempts == 1:
                    raise ValueError('synthetic first attempt failure')
                cancel.set()
            return super().decide(observation)
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('cancel_last')
        with pytest.raises(WorldError):
            run_round(store, LastAttemptPolicy('investment'), fence, cancelled=cancel.is_set)
        assert store.head()['round'] == 0
        assert store.decision('1:proposal:producer') is not None
        replay = ExamplePolicy('investment')
        cancel.clear()
        run_round(store, replay, fence)
        assert store.head()['round'] == 1
        assert not any(o['actorId'] == 'producer' and o['phase'] == 'proposal' for o in replay.observations)


def test_live_string_reflections_normalize_before_commit_and_replay(tmp_path):
    """Observed GLM responses followed the original documented array contract."""
    class ReflectingPolicy(ExamplePolicy):
        def decide(self, observation):
            raw = super().decide(observation)
            raw['stateUpdates'] = {'beliefs': ['Capacity remains constrained until the project completes.'],
                                   'plans': ['Review visible capacity before the next purchase.']}
            return raw
    spec = example_spec(periods=2)
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('reflection')
        run_to_horizon(store, ReflectingPolicy('investment'), fence)
        decision = store.decision('2:proposal:buyer')
        assert decision['stateUpdates']['beliefs'][0]['text'].startswith('Capacity remains')
        reflection = store.head()['actorStates']['buyer']['beliefs'][0]
        assert reflection['observationId'] == decision['observationId']
        assert reflection['basis']['kind'] == 'simulation_event'
        assert store.head()['round'] == 2
        final = store.head()
    with WorldStore(tmp_path / 'world.sqlite3', spec, read_only=True) as restored:
        assert restored.head() == final
        assert restored.decision('2:proposal:buyer') == decision


@pytest.mark.parametrize('updates', [{'beliefs': [True]}, {'plans': [12]}, {'priorityChanges': ['rewrite values']},
                                     {'beliefs': [{'observationId': 'other'}]},
                                     {'priorityChanges': [{'ruleId': 'invented', 'priorityId': 'profit', 'value': '99'}]}])
def test_malformed_actor_updates_reject_at_decision_boundary(updates):
    from app.services.world_simulation.contracts import validate_decision
    spec = example_spec()
    observation = build_observation(spec, initial_snapshot(spec), 'buyer', 1)
    with pytest.raises(WorldError):
        validate_decision(spec, {'actorId': 'buyer', 'observationId': observation['observationId'],
                                'intents': [], 'stateUpdates': updates}, 'buyer', observation, phase='proposal')


def test_only_second_attempt_receives_own_validation_feedback(tmp_path):
    class RepairPolicy(ExamplePolicy):
        supports_feedback = True
        def __init__(self):
            super().__init__('investment')
            self.seen = []
        def decide(self, observation, *, feedback=None):
            self.seen.append((observation['actorId'], observation['observationId'], clone(feedback)))
            result = super().decide(observation)
            if observation['actorId'] == 'buyer' and observation['phase'] == 'proposal' and feedback is None:
                result['undeclared'] = True
            return result
    spec = example_spec(periods=1)
    policy = RepairPolicy()
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        run_round(store, policy, store.acquire_writer('repair'))
        buyer = [row for row in policy.seen if row[0] == 'buyer']
        assert len(buyer) == 2 and buyer[0][1] == buyer[1][1]
        assert buyer[0][2] is None
        assert buyer[1][2] == {'code': 'invalid_decision', 'message': 'Actor response contains unsupported fields'}
        assert all(row[2] is None for row in policy.seen if row[0] != 'buyer')


def test_exhaustion_reports_safe_validation_code_not_provider_exception(tmp_path):
    class BadPolicy(ExamplePolicy):
        def decide(self, observation):
            raise RuntimeError('PRIVATE_PROVIDER_EXCEPTION_SENTINEL')
    spec = example_spec(periods=1)
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        with pytest.raises(WorldError) as error:
            run_round(store, BadPolicy('investment'), store.acquire_writer('bad'))
        assert error.value.details['lastErrorCode'] == 'policy_decision_failed'
        assert 'SENTINEL' not in canonical_json(error.value.to_dict())
        assert store.head()['round'] == 0
