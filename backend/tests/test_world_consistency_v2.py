"""Version isolation and real causal effects for server-bound review scope."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from app.services.world_simulation.contracts import WorldError, digest
from app.services.world_simulation.controller import PolicyResponse, run_round
from app.services.world_simulation.review import MODE, MODE_V2, KINDS, review_mode, validate_assessment
from app.services.world_simulation.store import WorldStore
from test_world_consistency_controller import RevisingPolicy, assessment, specification

pytestmark = pytest.mark.guarded_runner


def compact():
    return {'status': 'clear', 'checks': [{'kind': k, 'explanation': 'The final decision follows the visible facts and declared goals.'}
                                         for k in sorted(KINDS)]}


class V2Policy(RevisingPolicy):
    decision_review = MODE_V2

    def decide(self, obs, *, review=None):
        response = super().decide(obs, review=review)
        if review is not None:
            return PolicyResponse(response.decision, response.usage, assessment=compact())
        return response


@pytest.mark.parametrize('domain', ['investment', 'coalition'])
def test_v2_real_effects_atomic_scope_and_version_locked_reopen(tmp_path, domain):
    spec = specification(domain)
    spec['policy']['decisionReview'] = MODE_V2
    policy = V2Policy(domain)
    path = tmp_path / 'world.sqlite3'
    actor = 'buyer' if domain == 'investment' else 'org_c'
    slot = f'1:proposal:{actor}'
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('first')
        head = run_round(store, policy, fence)
        if domain == 'investment':
            assert head['accounts']['buyer_stock']['balance'] == '2'
        else:
            assert not [v for v in store.rounds()[0]['resolutions'] if v['actorId'] == 'org_c']
        receipt = store.consistency_receipt(slot)
        assert receipt['mode'] == MODE_V2
        assert receipt['observationHash'] == digest(store.observation(slot))
        assert receipt['candidateHash'] == digest(receipt['candidate'])
        assert receipt['finalDecisionHash'] == digest(store.decision(slot))
        assert receipt['assessment'] == compact()
        assert all(set(c) == {'kind', 'explanation'} for c in receipt['assessment']['checks'])
        assert [a['purpose'] for a in store.budget_summary()['attempts'] if a['slot'] == slot] == ['candidate', 'revision']
        store.release_writer(fence)
    calls = list(policy.calls)
    with WorldStore(path, read_only=True) as store:
        assert store.consistency_receipt(slot) == receipt and store.head() == head
    old_mode = deepcopy(spec)
    old_mode['policy']['decisionReview'] = MODE
    with pytest.raises(WorldError, match='specification differs'):
        WorldStore(path, old_mode)
    assert policy.calls == calls


def test_v1_reference_validation_is_not_weakened_by_v2():
    obs = {'actor': {'objectives': ['One goal']}, 'world': {}}
    decision = {'intents': []}
    v1 = assessment(obs, decision)
    assert validate_assessment(v1, obs, decision) == v1
    with pytest.raises(WorldError):
        validate_assessment(compact(), obs, decision)
    with pytest.raises(WorldError):
        validate_assessment(v1, obs, decision, mode=MODE_V2)
    v1['checks'][0]['intentIndices'] = [0]
    with pytest.raises(WorldError):
        validate_assessment(v1, obs, decision, mode=MODE)
    assert validate_assessment(compact(), obs, decision, mode=MODE_V2) == compact()


@pytest.mark.parametrize('mutation', ['extra_reference', 'missing_kind', 'duplicate_kind', 'long_text', 'empty_text', 'extra_status'])
def test_v2_closed_schema_keeps_substantive_obligations(mutation):
    value = compact()
    if mutation == 'extra_reference':
        value['checks'][0]['intentIndices'] = []
    elif mutation == 'missing_kind':
        value['checks'].pop()
    elif mutation == 'duplicate_kind':
        value['checks'][0]['kind'] = value['checks'][1]['kind']
    elif mutation == 'long_text':
        value['checks'][0]['explanation'] = 'x' * 401
    elif mutation == 'empty_text':
        value['checks'][0]['explanation'] = ' '
    else:
        value['passed'] = True
    with pytest.raises(WorldError):
        validate_assessment(value, {'actor': {'objectives': []}}, {'intents': []}, mode=MODE_V2)


def test_v2_unresolved_revision_commits_flagged_without_a_third_call(tmp_path):
    class Unresolved(V2Policy):
        def decide(self, obs, *, review=None):
            result = super().decide(obs, review=review)
            if review is not None and obs['actorId'] == 'buyer':
                result.assessment['status'] = 'unresolved'
            return result
    spec = specification()
    spec['policy']['decisionReview'] = MODE_V2
    policy = Unresolved('investment')
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('test')
        head = run_round(store, policy, fence)
        assert head['round'] == 1 and store.decision('1:proposal:buyer')['consistencyStatus'] == 'unresolved'
        assert store.withheld_consistency_receipt('1:proposal:buyer')['state'] == 'withheld'
        assert [c[2] for c in policy.calls if c[:2] == ('buyer', 'proposal')] == [False, True]
        with pytest.raises(WorldError) as caught:  # Nothing more to dispatch: the horizon is committed.
            run_round(store, policy, fence)
        assert caught.value.code == 'horizon_complete'


def test_compiler_preserves_v2_pin_and_legacy_default():
    from test_world_compiler import compile_proposal, proposal
    raw = proposal()
    raw['policy'] = {'decisionReview': MODE_V2}
    assert review_mode(compile_proposal(raw)) == MODE_V2
    assert review_mode(compile_proposal()) is None


def test_v2_directed_preregistration_and_quote_without_dispatch():
    from decimal import Decimal
    from app.services.world_simulation import consistency_evaluation as replay
    from app.services.world_simulation.artifacts import atomic_json
    from test_world_consistency_evaluation import factory_for
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/server-bound-review/live-policy.json').read_text())
    manifest = replay.preregister(config, '1.25')
    calls = []
    factory, clients = factory_for(manifest, calls)
    try:
        quotes = []
        for case in manifest['cases']:
            policy = factory(case['spec'])
            assert policy.decision_review == MODE_V2
            quotes.append(policy.reservation(case['actorPayload']['observation'], review=case['actorPayload']['candidateDecision']))
            policy.close()
        assert not calls and sum(Decimal(q['costUsd']) for q in quotes) <= Decimal('1.25')
        atomic_json(sys.modules['main_offline_guard'].root / 'reviewed-consistency-preregistration.json', manifest)
    finally:
        for client in clients:
            client.close()


def test_v2_directed_actual_sdk_journal_and_resume(tmp_path):
    from app.services.world_simulation import consistency_evaluation as replay
    from test_world_consistency_evaluation import factory_for
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/server-bound-review/live-policy.json').read_text())
    manifest = replay.preregister(config, '1.25')
    config['authorization'] = {'manifestHash': manifest['manifestHash'], 'offlineGatesPassed': True,
                               'pricingVerified': True, 'evidenceRefs': ['fixture://offline-only']}
    calls = []
    factory, clients = factory_for(manifest, calls)
    try:
        first = replay.run_evaluation(tmp_path / 'directed', factory, config)
        assert first['completedCases'] == first['matchedCases'] == 12
        assert first['diagnosticGate'] == 'incomplete' and first['promotionAuthorized'] is False
        assert len(calls) == 12 and first['budget']['unknown']['costUsd'] == '0'
        second = replay.run_evaluation(tmp_path / 'directed', factory, config)
        assert second == first and len(calls) == 12
    finally:
        for client in clients:
            client.close()
