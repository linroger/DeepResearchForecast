"""M5 scripted proof only: real controller/store, guarded offline execution."""
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace

import pytest

from app.services.world_simulation import evaluation
from app.services.world_simulation.contracts import WorldError, clone, digest, initial_snapshot
from app.services.world_simulation.controller import PolicyResponse, run_round
from app.services.world_simulation.examples import ExamplePolicy
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.store import WorldStore

pytestmark = pytest.mark.guarded_runner
PRICING = {'mode': 'scripted', 'policyId': 'm5-scripted-proof/v1'}


class ScriptedPolicy(ExamplePolicy):
    evaluation_mode = 'scripted'

    def decide(self, obs):
        result = super().decide(obs)
        if obs['phase'] == 'proposal':
            if self.domain == 'investment' and obs['actorId'] == 'buyer':
                amount = str(int(obs['world']['metrics']['capacity']['value']) - 1)
                result['intents'][0]['parameters'] = {'quantity': amount, 'price': amount}
            if self.domain == 'coalition' and obs['actorId'] == 'org_c':
                result['intents'] = ([{'templateId': 'program_vote', 'parameters': {'support': False}}]
                                     if obs['world']['relations']['coalition_ab']['value'] == 'allied' else [])
        return result


class ScriptedFactory:
    evaluation_mode = 'scripted'

    def __init__(self, policy_type=ScriptedPolicy):
        self.specs = []
        self.policy_type = policy_type

    def __call__(self, spec):
        self.specs.append(clone(spec))
        domain = next(domain for domain in evaluation.DOMAINS if spec['simulationId'].startswith('m5-' + domain))
        return self.policy_type(domain)


@pytest.fixture(scope='module')
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp('m5-completed')
    factory = ScriptedFactory()
    report = evaluation.run_evaluation(root, factory, PRICING)
    return root, factory, report


def test_fixed_detached_matrix_and_matched_physics():
    cases = evaluation.build_cases()
    assert len(cases) == len({c['evaluationId'] for c in cases}) == 36
    assert len({c['pairId'] for c in cases}) == 18
    for before, control in zip(cases[::2], cases[1::2], strict=True):
        assert before['arm'] == 'reflexive'
        assert control['arm'] == 'external-feedback-ablation'
        masked_spec = clone(control['spec'])
        mask = masked_spec.pop('evaluationObservationMask')
        assert mask == {'schemaVersion': evaluation.MASK_SCHEMA, 'maskId': before['pairId']}
        assert before['spec'] == masked_spec
        assert len(masked_spec['actors']) == len(masked_spec['periods']) == 4
        assert masked_spec['assumptions'][-1]['assumptionId'] == evaluation.VERSION
    assert digest(cases) == digest(evaluation.build_cases())
    cases[0]['spec']['actors'].clear()
    assert len(evaluation.build_cases()[0]['spec']['actors']) == 4


@pytest.mark.parametrize('case', evaluation.build_cases()[1::2], ids=lambda c: c['evaluationId'])
def test_real_builder_masks_only_fixed_external_value_before_digest(case):
    spec, comparison = case['spec'], case['comparison']
    state = initial_snapshot(spec)
    modified = clone(state)
    modified[comparison['section']][comparison['recordId']]['value'] = comparison['changed']
    original_state = clone(modified)
    for phase in ('proposal', 'response'):
        baseline = build_observation(spec, state, comparison['actorId'], comparison['afterRound'], phase)
        masked = build_observation(spec, modified, comparison['actorId'], comparison['afterRound'], phase)
        assert masked == baseline
        unmasked_spec = clone(spec)
        unmasked_spec.pop('evaluationObservationMask')
        unmasked = build_observation(unmasked_spec, modified, comparison['actorId'], comparison['afterRound'], phase)
        assert unmasked != masked
        assert unmasked['options'] == masked['options']
        assert unmasked['inbox'] == masked['inbox']
        assert unmasked['messages'] == masked['messages']
        assert unmasked['privateState'] == masked['privateState']
        assert unmasked['world']['accounts'] == masked['world']['accounts']
        unmasked['world'][comparison['section']][comparison['recordId']]['value'] = comparison['baseline']
        unmasked.pop('observationId')
        assert masked['observationId'] == digest(unmasked)
        assert 'evaluationObservationMask' not in masked
        # A later epoch retains new permitted feedback.
        later = build_observation(spec, modified, comparison['actorId'], comparison['afterRound'] + 1, phase)
        assert later['world'][comparison['section']][comparison['recordId']]['value'] == comparison['changed']
    assert modified == original_state


@pytest.mark.parametrize('change', ['path', 'unknown', 'physics', 'inbox_limit', 'digest'])
def test_mask_rejects_user_defined_interventions(change):
    case = evaluation.build_cases()[1]
    spec = case['spec']
    observation = build_observation(spec, initial_snapshot(spec), 'buyer', 3)
    if change != 'digest':
        observation.pop('observationId')
    if change == 'path':
        spec['evaluationObservationMask']['paths'] = ['world.accounts.buyer_cash']
    elif change == 'unknown':
        spec['evaluationObservationMask']['maskId'] = 'caller-defined'
    elif change == 'physics':
        spec['initialState']['accounts']['buyer_cash']['balance'] = '999'
    elif change == 'inbox_limit':
        spec['limits']['maxInboxItems'] = 1
    with pytest.raises(WorldError, match='Mask'):
        evaluation.apply_observation_mask(spec, observation)


def test_complete_scripted_matrix_keeps_explanation_review_and_no_live_claim(completed):
    root, factory, report = completed
    assert len(factory.specs) == 36
    assert set(report['cases'].values()) == {'completed'}
    assert report['contrastGate'] == 'passed'
    assert len(report['requiredContrasts']) == 18
    assert report['rubricGate'] == 'incomplete'
    assert report['budget']['reserved']['costUsd'] == '0'
    assert report['allocatedUsd'] == '24.999999999984'
    assert not report['calibrationClaim'] and not report['liveModelRealismClaim'] and not report['promotionAuthorized']
    for domain in report['domains'].values():
        assert domain['completedCases'] == domain['plannedCases'] == 12
        assert domain['denominatorPoints'] == 96
        assert domain['qualitativeReviewedCases'] == 0
        assert domain['status'] == 'incomplete'
        assert Decimal(domain['percentLowerBound']) <= 75
    # The real stores, observations and scored comparison are linked in artifacts.
    case = evaluation.build_cases()[0]
    with WorldStore(root / case['evaluationId'] / 'world.sqlite3', read_only=True) as store:
        assert store.head()['round'] == 4
        assert len(store.history()) == 5
        assert store.observation('3:proposal:buyer')['world']['metrics']['capacity']['value'] == '5'


def test_completed_batch_never_calls_factory_again(completed):
    root, _, prior = completed
    factory = ScriptedFactory()
    assert evaluation.run_evaluation(root, factory, PRICING) == prior
    assert factory.specs == []


def test_feedback_history_does_not_disclose_masked_external_update(completed):
    root, _, _ = completed
    for case in evaluation.build_cases():
        comparison = case['comparison']
        with WorldStore(root / case['evaluationId'] / 'world.sqlite3', read_only=True) as store:
            slot = f'{comparison["afterRound"]}:proposal:{comparison["actorId"]}'
            observation = store.observation(slot)
            events = observation['privateState']['lastObservedEvents']
            physical = store.history()[comparison['afterRound'] - 1]
            blocked_template = {'investment': 'expand', 'trade': 'restrict_a', 'coalition': 'coalition'}[case['domain']]
            blocked_commitments = {cid for cid, item in physical['commitments'].items()
                                   if item['templateId'] == blocked_template}
            assert not any(event['details'].get('commitmentId') in blocked_commitments for event in events)
            assert not set(observation['world']['commitments']) & blocked_commitments
            if case['domain'] == 'investment':
                assert 'raw_supply' not in observation['world']['accounts']
                assert not any(event['details'].get('flowId') == 'production' for event in events)
                producer = store.observation('3:proposal:producer')
                assert any(event['details'].get('flowId') == 'production'
                           for event in producer['privateState']['lastObservedEvents'])
                assert observation['world']['accounts']['buyer_cash'] == physical['accounts']['buyer_cash']
                assert observation['world']['accounts']['buyer_stock'] == physical['accounts']['buyer_stock']
                assert observation['privateState']['lastActionResults']
                assert all(result['actorId'] == 'buyer' for result in observation['privateState']['lastActionResults'])
                # Consent is still delivered with exact terms to the producer.
                consent = store.observation('3:response:producer')
                assert consent['inbox'][0]['termsVersion'] == 1
                assert consent['inbox'][0]['terms']['quantity'] == (
                    comparison['after'] if case['arm'] == 'reflexive' else comparison['before'])
            if case['domain'] == 'coalition':
                assert events == []  # C was not party to the private formation/consent.
                assert not observation['inbox'] and not observation['ownOffers']


def test_changed_manifest_rejected_before_any_factory(completed):
    root, _, _ = completed
    factory = ScriptedFactory()
    with pytest.raises(WorldError, match='Frozen evaluation inputs changed'):
        evaluation.run_evaluation(root, factory, PRICING, max_usd='24')
    assert factory.specs == []


class MeteredUnknown(ScriptedPolicy):
    # External=True exercises the real controller's metering path, but decide
    # below is a local exception only: no SDK, socket, subprocess or provider.
    external = True

    def reservation(self, observation):
        return {'tokens': 100, 'costUsd': '0.2'}

    def decide(self, observation):
        raise RuntimeError('scripted ambiguous dispatch')


def test_unknown_concurrent_attempts_remain_reserved_and_stopped_in_denominator(tmp_path):
    factory = ScriptedFactory(MeteredUnknown)
    report = evaluation.run_evaluation(tmp_path, factory, PRICING)
    assert set(report['cases'].values()) == {'budget_stopped'}
    assert report['budget']['reserved']['costUsd'] == '21.6'
    assert report['budget']['unknown']['costUsd'] == '21.6'
    assert report['budget']['actual']['costUsd'] == '0'
    assert report['attempts'] == 108
    assert report['contrastGate'] == report['rubricGate'] == 'incomplete'
    for domain in report['domains'].values():
        assert domain['incompleteCases'] == 12
        assert domain['earnedPoints'] == 0
        assert domain['denominatorPoints'] == 96
    replay = ScriptedFactory()
    assert evaluation.run_evaluation(tmp_path, replay, PRICING) == report
    assert replay.specs == []


class MeteredCheap(ScriptedPolicy):
    external = True

    def reservation(self, observation):
        return {'tokens': 100, 'costUsd': '0.1'}

    def decide(self, observation):
        return PolicyResponse(super().decide(observation), {'tokens': 1, 'costUsd': '0.001'})


class FeedbackMetered(MeteredCheap):
    supports_feedback = True

    def __init__(self, domain, *, always_invalid=False):
        super().__init__(domain)
        self.always_invalid = always_invalid
        self.quoted = []
        self.dispatched = []

    def reservation(self, observation, *, feedback=None):
        self.quoted.append((observation['observationId'], clone(feedback)))
        return {'tokens': 200 if feedback else 100, 'costUsd': '0.02' if feedback else '0.01'}

    def decide(self, observation, *, feedback=None):
        self.dispatched.append((observation['observationId'], clone(feedback)))
        decision = ScriptedPolicy.decide(self, observation)
        if (observation['actorId'] == 'buyer' and observation['round'] == 1
                and observation['phase'] == 'proposal' and (feedback is None or self.always_invalid)):
            decision['stateUpdates'] = {'objectives': ['unauthorized rewrite']}
        return PolicyResponse(decision, {'tokens': 1, 'costUsd': '0.001'})


def test_reserved_policy_forwards_matching_feedback_and_supports_legacy():
    spec = evaluation.preregister(PRICING)['cases'][0]['spec']
    observation = build_observation(spec, initial_snapshot(spec), 'buyer', 1)
    candidate = FeedbackMetered('investment')
    policy = evaluation._ReservedPolicy(candidate, spec, 'scripted')
    assert policy.supports_feedback is True
    feedback = {'code': 'unauthorized_actor_update',
                'message': 'Stable goals/values/incentives cannot be rewritten by a decision'}
    for value in (None, feedback):
        quote = policy.reservation(observation, feedback=value)
        policy.decide(observation, feedback=value)
        assert quote['tokens'] == (100 if value is None else 200)
        assert candidate.quoted[-1] == candidate.dispatched[-1] == (observation['observationId'], value)
    legacy = evaluation._ReservedPolicy(MeteredCheap('investment'), spec, 'scripted')
    assert legacy.supports_feedback is False
    assert legacy.reservation(observation, feedback=feedback) == {'tokens': 100, 'costUsd': '0.1'}
    assert isinstance(legacy.decide(observation, feedback=feedback), PolicyResponse)


@pytest.mark.parametrize('always_invalid', [False, True])
def test_controller_feedback_keeps_quote_dispatch_and_two_attempt_accounting(tmp_path, always_invalid):
    case = evaluation.preregister(PRICING)['cases'][0]
    candidate = FeedbackMetered('investment', always_invalid=always_invalid)
    receipt = evaluation._execute(tmp_path, case, lambda spec: candidate, 'scripted')
    attempts = [a for a in receipt['budget']['attempts'] if a['slot'] == '1:proposal:buyer']
    assert len(attempts) == 2
    assert [a['ordinal'] for a in attempts] == [1, 2]
    assert [a['reserved']['tokens'] for a in attempts] == [100, 200]
    assert receipt['budget']['unknown']['costUsd'] == '0'
    assert Decimal(receipt['budget']['actual']['costUsd']) == Decimal(len(candidate.dispatched)) * Decimal('0.001')
    by_observation = lambda values: {
        oid: [feedback for observed, feedback in values if observed == oid] for oid, _ in values}
    assert by_observation(candidate.quoted) == by_observation(candidate.dispatched)
    retry_feedback = next(value for _, value in candidate.dispatched if value is not None)
    assert retry_feedback['code'] == 'unauthorized_actor_update'
    assert retry_feedback['message'] == 'Stable goals/values/incentives cannot be rewritten by a decision'
    if always_invalid:
        assert receipt['status'] == 'failed' and receipt['completedRound'] == 0
        assert receipt['errorCode'] == 'required_decision_failed'
        assert receipt['errorDetails'] == {'lastErrorCode': retry_feedback['code'],
                                           'lastErrorMessage': retry_feedback['message']}
        assert len(candidate.dispatched) == 5
    else:
        assert receipt['status'] == 'completed' and receipt['completedRound'] == 4
        assert len(candidate.dispatched) == 21
        assert 'errorDetails' not in receipt


@pytest.mark.parametrize('kind', ['sanitized', 'unknown', 'other_world_error', 'malformed'])
def test_failure_receipt_retains_only_coordinator_diagnostic_allowlist(tmp_path, kind):
    case = evaluation.preregister(PRICING)['cases'][0]

    def failing_factory(spec):
        if kind == 'unknown':
            raise RuntimeError('DO_NOT_SERIALIZE_EXCEPTION_TEXT')
        details = {'lastErrorCode': 'invalid_decision', 'lastErrorMessage': 'Actor response must be an object',
                   'rawResponse': 'DO_NOT_SERIALIZE_EXTRA_DETAIL'}
        if kind == 'malformed':
            details.update(lastErrorCode={'raw': 'DO_NOT_SERIALIZE_NESTED'}, lastErrorMessage=['raw'])
        raise WorldError('required_decision_failed' if kind != 'other_world_error' else 'policy_transport_failed',
                         'DO_NOT_SERIALIZE_EXCEPTION_TEXT', details=details)

    receipt = evaluation._execute(tmp_path, case, failing_factory, 'scripted')
    serialized = json.dumps(receipt)
    assert 'DO_NOT_SERIALIZE' not in serialized
    if kind == 'sanitized':
        assert receipt['errorDetails'] == {'lastErrorCode': 'invalid_decision',
                                           'lastErrorMessage': 'Actor response must be an object'}
    else:
        assert 'errorDetails' not in receipt


def test_known_tiny_usage_completes_when_cumulative_quotes_exceed_share(tmp_path):
    report = evaluation.run_evaluation(tmp_path, ScriptedFactory(MeteredCheap), PRICING)
    assert set(report['cases'].values()) == {'completed'}
    assert Decimal(report['budget']['reserved']['costUsd']) > Decimal(report['allocatedUsd'])
    assert Decimal(report['budget']['exposure']['costUsd']) < Decimal(report['allocatedUsd'])
    assert Decimal(report['budget']['actual']['costUsd']) == Decimal(report['attempts']) * Decimal('0.001')
    assert report['budget']['unknown']['costUsd'] == '0'
    cid = evaluation.build_cases()[0]['evaluationId']
    receipt = json.loads((tmp_path / cid / 'receipt.json').read_text())
    assert receipt['completedRound'] == 4
    assert len(receipt['budget']['attempts']) == len(receipt['calls']) == 20
    assert receipt['budget']['reserved']['costUsd'] == '2'
    assert receipt['budget']['exposure']['costUsd'] == '0.02'
    replay = ScriptedFactory(MeteredCheap)
    assert evaluation.run_evaluation(tmp_path, replay, PRICING) == report
    assert replay.specs == []


class MeteredActualCost(MeteredCheap):
    def decide(self, observation):
        return PolicyResponse(ScriptedPolicy.decide(self, observation), {'tokens': 100, 'costUsd': '0.1'})


def test_actual_cost_exhaustion_preserves_committed_counts_and_incomplete_scores(tmp_path):
    report = evaluation.run_evaluation(tmp_path, ScriptedFactory(MeteredActualCost), PRICING)
    assert set(report['cases'].values()) == {'budget_stopped'}
    assert report['budget']['reserved']['costUsd'] == '21.6'
    assert report['budget']['actual']['costUsd'] == '21.6'
    assert report['budget']['unknown']['costUsd'] == '0'
    assert report['attempts'] == 216
    # Every case commits round 1 before actual cost exhausts its share. Those
    # actual operations remain counted, while behavior scores stay incomplete.
    for domain in report['domains'].values():
        assert domain['status'] == 'incomplete'
        assert domain['operations']['totalCommittedIntents'] > 0
        assert domain['operations']['committedAbstentions'] > 0
        assert domain['operations']['unobservedCases'] == 0
    cid = evaluation.build_cases()[0]['evaluationId']
    receipt = json.loads((tmp_path / cid / 'receipt.json').read_text())
    assert receipt['score'] is None and receipt['completedRound'] == 1
    assert receipt['operations'] == {'totalCommittedIntents': 3, 'rejectedCommittedIntents': 0,
                                     'committedAbstentions': 2}


def test_store_caps_concurrent_actual_unknown_and_inflight_exposure(tmp_path):
    spec = evaluation.preregister(PRICING)['cases'][0]['spec']
    entered = threading.Barrier(4)  # Three affordable dispatches plus this test.
    release = threading.Event()

    class ConcurrentMixed(MeteredUnknown):
        def __init__(self, domain):
            super().__init__(domain)
            self.lock = threading.Lock()
            self.dispatches = 0

        def decide(self, observation):
            with self.lock:
                ticket = self.dispatches
                self.dispatches += 1
            entered.wait(timeout=10)
            assert release.wait(timeout=10)
            if ticket == 0:
                return PolicyResponse(ScriptedPolicy.decide(self, observation), {'tokens': 50, 'costUsd': '0.1'})
            raise RuntimeError('scripted unknown exposure')

    candidate = ConcurrentMixed('investment')
    policy = evaluation._ReservedPolicy(candidate, spec, 'scripted')
    with WorldStore(tmp_path / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('concurrent-budget-proof')
        with ThreadPoolExecutor(max_workers=1) as runner:
            task = runner.submit(run_round, store, policy, fence)
            try:
                entered.wait(timeout=10)
                inflight = store.budget_summary()
                assert len(inflight['attempts']) == 3
                assert inflight['actual']['costUsd'] == '0'
                assert inflight['unknown']['costUsd'] == inflight['exposure']['costUsd'] == '0.6'
                assert Decimal(inflight['exposure']['costUsd']) <= Decimal(spec['limits']['maxCostUsd'])
            finally:
                release.set()
            with pytest.raises(WorldError, match='allowance exhausted'):
                task.result(timeout=10)
        closed = store.budget_summary()
        assert closed['actual']['costUsd'] == '0.1'
        assert closed['unknown']['costUsd'] == '0.4'
        assert closed['exposure']['costUsd'] == '0.5'
        assert candidate.dispatches == 3
        assert all(attempt['ordinal'] <= 2 for attempt in closed['attempts'])
        assert store.head()['round'] == 0
        store.release_writer(fence)


def test_new_phase_uses_only_supplied_remaining_allowance(tmp_path):
    # Synthetic earlier-phase reconciliation, not evidence of actual live cost.
    closed_prior_exposure = Decimal('19.96')
    remaining = Decimal('25') - closed_prior_exposure
    report = evaluation.run_evaluation(tmp_path, ScriptedFactory(MeteredActualCost), PRICING,
                                       max_usd=str(remaining))
    assert report['allocatedUsd'] == report['maxCostUsd'] == '5.04'
    assert set(report['cases'].values()) == {'budget_stopped'}
    assert Decimal(report['budget']['exposure']['costUsd']) <= remaining
    assert closed_prior_exposure + Decimal(report['budget']['exposure']['costUsd']) <= 25
    assert all(domain['incompleteCases'] == 12 for domain in report['domains'].values())


def test_interruption_holds_whole_share_and_never_redispatches(tmp_path, monkeypatch):
    real_execute = evaluation._execute
    calls = []

    def interrupted(root, case, factory, mode):
        calls.append(case['evaluationId'])
        raise KeyboardInterrupt('scripted process loss before receipt')

    monkeypatch.setattr(evaluation, '_execute', interrupted)
    with pytest.raises(KeyboardInterrupt):
        evaluation.run_evaluation(tmp_path, ScriptedFactory(), PRICING)
    monkeypatch.setattr(evaluation, '_execute', real_execute)
    factory = ScriptedFactory()
    report = evaluation.run_evaluation(tmp_path, factory, PRICING)
    assert len(factory.specs) == 35
    assert report['cases'][calls[0]] == 'interrupted'
    assert report['budget']['unknown']['costUsd'] == '0.694444444444'
    assert report['domains']['investment']['incompleteCases'] == 1
    assert report['domains']['investment']['denominatorPoints'] == 96
    assert report['contrastGate'] == 'incomplete'


def test_preregistration_written_before_factory_and_denies_implicit_external(tmp_path):
    class CheckingFactory(ScriptedFactory):
        def __call__(self, spec):
            manifest = json.loads((tmp_path / 'preregistration.json').read_text())
            assert len(manifest['cases']) == 36
            assert manifest['rubric'] == evaluation.RUBRIC
            return super().__call__(spec)
    evaluation.run_evaluation(tmp_path, CheckingFactory(), PRICING)


@pytest.mark.parametrize('maximum', ['25.01', '0', '-1', 'NaN', 'Infinity', 25.0])
def test_invalid_budget_never_invokes_factory(tmp_path, maximum):
    factory = ScriptedFactory()
    with pytest.raises(WorldError):
        evaluation.run_evaluation(tmp_path, factory, PRICING, max_usd=maximum)
    assert factory.specs == []


def test_external_mode_needs_coordinator_manifest_bound_price_and_gates(tmp_path):
    class ExternalFactory(ScriptedFactory):
        evaluation_mode = 'external'
    factory = ExternalFactory()
    pricing = {'mode': 'external', 'policyId': 'glm-5.3-pinned', 'policy': {}}
    with pytest.raises(WorldError, match='Coordinator'):
        evaluation.run_evaluation(tmp_path, factory, pricing)
    assert factory.specs == []


def test_missing_real_mask_hook_fails_before_factory(tmp_path, monkeypatch):
    from app.services.world_simulation import observations
    real = observations.build_observation

    def unmasked(spec, *args, **kwargs):
        spec = clone(spec)
        spec.pop('evaluationObservationMask', None)
        return real(spec, *args, **kwargs)

    monkeypatch.setattr(observations, 'build_observation', unmasked)
    factory = ScriptedFactory()
    with pytest.raises(WorldError, match='Real observation builder'):
        evaluation.run_evaluation(tmp_path, factory, PRICING)
    assert factory.specs == []


def test_batch_exclusion_and_symlink_fail_closed(tmp_path):
    with evaluation._batch_lock(tmp_path):
        with pytest.raises(WorldError, match='Another evaluator'):
            evaluation.run_evaluation(tmp_path, ScriptedFactory(), PRICING)
    link = tmp_path / 'alias'
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(WorldError, match='symlink'):
        evaluation.run_evaluation(link, ScriptedFactory(), PRICING)


def test_same_coalition_decision_fails_required_contrast(completed):
    root, _, _ = completed
    manifest = json.loads((root / 'preregistration.json').read_text())
    state = json.loads((root / 'status.json').read_text())
    receipts = evaluation._load_receipts(root, manifest, state)
    case = next(c for c in manifest['cases'] if c['domain'] == 'coalition')
    receipts[case['evaluationId']]['score']['observedActions'] = ['wait', 'wait']
    contrast = next(c for c in evaluation._contrasts(manifest['cases'], receipts) if c['pairId'] == case['pairId'])
    assert contrast['status'] == 'failed'


@pytest.mark.parametrize('reviewer_type', ['human', 'independent-agent'])
def test_qualitative_review_is_bound_and_missing_case_keeps_denominator(completed, tmp_path, reviewer_type):
    root, _, _ = completed
    manifest = json.loads((root / 'preregistration.json').read_text())
    state = json.loads((root / 'status.json').read_text())
    receipts = evaluation._load_receipts(root, manifest, state)
    first = manifest['cases'][0]
    cid = first['evaluationId']
    receipt = receipts[cid]
    item = {'evaluationId': cid, 'traceHash': receipt['traceHash'], 'reviewer': 'Scripted test reviewer',
                'reviewerType': reviewer_type, 'score': 2,
                'note': 'Synthetic test of review import only; no actual qualitative review occurred.',
                'evidenceRefs': [r['decisionId'] for r in receipt['score']['evidenceRefs']]}
    evaluation._write(tmp_path / 'qualitative-review.json', {'manifestHash': manifest['manifestHash'], 'reviews': [item]})
    scores = evaluation._qualitative_scores(tmp_path, manifest, receipts)
    assert scores == {cid: 2}
    missing = evaluation._group_report(manifest['cases'][:2], {cid: receipt}, scores)
    assert missing['denominatorPoints'] == 16 and missing['incompleteCases'] == 1
    assert missing['qualitativeReviewedCases'] == 1
    assert missing['status'] == 'incomplete'
    item['traceHash'] = 'tampered'
    evaluation._write(tmp_path / 'qualitative-review.json', {'manifestHash': manifest['manifestHash'], 'reviews': [item]})
    with pytest.raises(WorldError, match='Qualitative score'):
        evaluation._qualitative_scores(tmp_path, manifest, receipts)


def _external_fixture():
    """Metadata for synthetic admission checks, never live tariff evidence."""
    return {
        'mode': 'external', 'policyId': 'synthetic-admission/v1', 'maxOutputTokens': 2048,
        'policy': {
            'provider': 'glm', 'model': 'fixture', 'baseUrl': 'https://fixture.invalid/v1',
            'timeoutSeconds': 30, 'maxInputTokens': 32000, 'reasoningEffort': 'low',
            'pricing': {
                'provider': 'glm', 'model': 'fixture', 'baseUrl': 'https://fixture.invalid/v1',
                'inputUsdPerMillion': '2', 'outputUsdPerMillion': '6',
                'contextWindowTokens': 64000, 'maxOutputTokens': 8192, 'inputOverheadTokens': 1024,
                'outputTokenParameter': 'max_completion_tokens', 'maxOutputIncludesReasoning': True,
                'source': {'reference': 'fixture://not-live-pricing', 'asOf': '2026-10-17T00:00:00Z'},
            },
        },
    }


def _undispatched_candidate(spec):
    """Construct only the state inspected by admission, with no SDK or HTTP I/O."""
    from app.services.world_simulation.policy import StrictHTTPPolicy

    policy = object.__new__(StrictHTTPPolicy)
    config, limits = spec['policy'], spec['limits']
    policy.provider, policy.model, policy.base_url = config['provider'], config['model'], config['baseUrl']
    policy.pricing = clone(config['pricing'])
    policy.max_input, policy.max_output = config['maxInputTokens'], limits['maxOutputTokens']
    policy.timeout, policy.context = config['timeoutSeconds'], policy.pricing['contextWindowTokens']
    policy._input_rate, policy._output_rate = Decimal('2'), Decimal('6')
    policy._overhead, policy._output_parameter = 1024, 'max_completion_tokens'
    policy._reasoning_effort = config['reasoningEffort']
    policy.max_intents, policy._max_messages = limits['maxIntentsPerPhase'], limits['maxInboxItems']
    policy._max_message_chars = limits['maxMessageChars']
    policy._actors = frozenset(a['actorId'] for a in spec['actors'])
    policy._client = SimpleNamespace(close=lambda: None)
    return policy


@pytest.mark.parametrize('field,bad', [
    ('provider', 'other'), ('model', 'other'), ('base_url', 'https://other.invalid/v1'),
    ('pricing', {}), ('_input_rate', Decimal('0.01')), ('_output_rate', Decimal('0.01')),
    ('max_input', 64000), ('max_output', 8192), ('timeout', 120), ('context', 128000),
    ('_overhead', 1), ('_output_parameter', 'max_tokens'), ('_reasoning_effort', 'high'),
    ('max_intents', 10), ('_max_messages', 100), ('_max_message_chars', 3000), ('_actors', frozenset()),
])
def test_external_effective_configuration_must_match_sealed_case(field, bad):
    case = evaluation.preregister(_external_fixture())['cases'][0]
    candidate = _undispatched_candidate(case['spec'])
    evaluation._bind_external_policy(candidate, case['spec'])
    setattr(candidate, field, bad)
    with pytest.raises(WorldError, match='pinned pricing and request bounds'):
        evaluation._bind_external_policy(candidate, case['spec'])


def test_authorized_factory_with_stale_effective_tariff_never_dispatches(tmp_path):
    pricing = _external_fixture()
    manifest = evaluation.preregister(pricing)
    pricing['authorization'] = {'manifestHash': manifest['manifestHash'], 'coordinator': 'scripted-test',
                                   'pricingVerified': True, 'offlineGatesPassed': True, 'evidenceRefs': ['fixture://only']}
    class MismatchedFactory:
        evaluation_mode = 'external'

        def __call__(self, spec):
            candidate = _undispatched_candidate(spec)
            candidate._input_rate = Decimal('0.001')
            return candidate
    report = evaluation.run_evaluation(tmp_path, MismatchedFactory(), pricing)
    assert set(report['cases'].values()) == {'failed'}
    assert report['attempts'] == 0
    assert report['budget']['reserved']['costUsd'] == '0'
    assert report['rubricGate'] == 'incomplete'
    for cid in report['cases']:
        receipt = json.loads((tmp_path / cid / 'receipt.json').read_text())
        assert receipt['errorCode'] == 'evaluation_policy_mismatch'


def test_receipt_before_status_crash_stays_incomplete_without_rerun(completed, tmp_path):
    root, _, _ = completed
    manifest = json.loads((root / 'preregistration.json').read_text())
    cid = manifest['cases'][0]['evaluationId']
    state = {'manifestHash': manifest['manifestHash'], 'cases': {
        case['evaluationId']: {'status': 'running' if case['evaluationId'] == cid else 'planned'}
        for case in manifest['cases']}}
    evaluation._write(tmp_path / 'preregistration.json', manifest)
    evaluation._write(tmp_path / 'status.json', state)
    (tmp_path / cid).mkdir()
    evaluation._write(tmp_path / cid / 'receipt.json', json.loads((root / cid / 'receipt.json').read_text()))
    report = evaluation.summarize_evaluation(tmp_path)
    assert report['cases'][cid] == 'interrupted'
    assert report['budget']['unknown'] == {'costUsd': '0.694444444444', 'tokens': 250000}
    assert report['domains']['investment']['incompleteCases'] == 12
    assert report['domains']['investment']['denominatorPoints'] == 96


def test_qualitative_review_can_complete_rubric_without_claiming_human_review(completed, tmp_path):
    root, _, _ = completed
    manifest = json.loads((root / 'preregistration.json').read_text())
    state = json.loads((root / 'status.json').read_text())
    receipts = evaluation._load_receipts(root, manifest, state)
    reviews = [{'evaluationId': cid, 'traceHash': r['traceHash'], 'reviewer': 'scripted-independent-review-fixture',
                    'reviewerType': 'independent-agent', 'score': 2, 'note': 'Fixture only, no actual qualitative verdict.',
                    'evidenceRefs': [ref['decisionId'] for ref in r['score']['evidenceRefs']]}
               for cid, r in receipts.items()]
    evaluation._write(tmp_path / 'qualitative-review.json', {'manifestHash': manifest['manifestHash'], 'reviews': reviews})
    qualitative = evaluation._qualitative_scores(tmp_path, manifest, receipts)
    for domain in evaluation.DOMAINS:
        report = evaluation._group_report([c for c in manifest['cases'] if c['domain'] == domain], receipts, qualitative)
        assert report['qualitativeReviewedCases'] == 12
        assert report['status'] == 'passed'
        assert Decimal(report['percentLowerBound']) >= 80
    reviews[0]['reviewerType'] = 'automated-heuristic'
    evaluation._write(tmp_path / 'qualitative-review.json', {'manifestHash': manifest['manifestHash'], 'reviews': reviews})
    with pytest.raises(WorldError, match='typed named reviewer'):
        evaluation._qualitative_scores(tmp_path, manifest, receipts)
