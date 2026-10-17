"""Offline launch admission: no configuration, SDK or provider is imported."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.guarded_runner


def load_launcher():
    path = Path(__file__).resolve().parents[2] / 'docs/handoff/reflexive-world-simulation/run_live_evaluation.py'
    spec = importlib.util.spec_from_file_location('world_evaluation_launch_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def launch(tmp_path):
    repository = tmp_path / 'source'
    repository.mkdir()
    (repository / 'frozen.py').write_text('FROZEN = True\n')
    notes, offline, output = repository / 'notes', tmp_path / 'offline', tmp_path / 'new-v2'
    old = tmp_path / 'old-v1'
    write(old / 'report.json', {'cases': {'original': 'failed'}, 'promotionAuthorized': False})
    phase = {'output': str(output), 'status': 'authorized_after_behavior_v2_gate',
             'limitUsd': '15.777849044336', 'evaluationVersion': 'm5-behavior/v2',
             'manifestHash': 'reviewed-preregistration',
             'policyFile': 'behavior-rerun/live-policy.json', 'recordDirectory': 'behavior-rerun'}
    budget = {'authorizedUsd': '25', 'activeOutput': str(output), 'phases': [
        {'output': str(old), 'status': 'closed_evaluated_no_promotion',
         'settledCeilingUsd': '9.222150955664',
         'reportSha256': hashlib.sha256((old / 'report.json').read_bytes()).hexdigest()}, phase]}
    write(notes / 'implementation-approval.json', {'live_evaluation_max_usd': '25.00'})
    write(notes / 'live-budget.json', budget)
    write(notes / 'live-policy.json', {'policyId': 'original-v1'})
    write(notes / 'live-launch-binding.json', {'manifestHash': 'original-v1'})
    write(notes / 'behavior-rerun/live-policy.json', {'policyId': 'new-v2'})
    write(offline / 'evidence/completed.json', {'exit_code': 0, 'shutdown_complete': True})
    write(offline / 'evidence/reviewed-preregistration.json', {'schemaVersion': 'm5-behavior/v2', 'manifestHash': 'reviewed-preregistration'})
    write(offline / 'verification-summary.json', {'sourceDrift': []})
    write(offline / 'source-manifest.json', {'frozen.py': hashlib.sha256((repository / 'frozen.py').read_bytes()).hexdigest()})
    return load_launcher(), repository, notes, offline, output, budget


def test_new_phase_selects_v2_and_only_original_remaining_budget_without_writes(launch):
    module, repo, notes, offline, output, _ = launch
    before = {p: p.read_bytes() for root in (repo, offline) for p in root.rglob('*') if p.is_file()}
    admitted = module.admit_launch(repo, notes, offline, output)
    assert admitted['maximum'] == '15.777849044336'
    assert admitted['version'] == 'm5-behavior/v2'
    assert admitted['recordDirectory'] == notes / 'behavior-rerun'
    assert admitted['pricingPath'] == notes / 'behavior-rerun/live-policy.json'
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not output.exists()


@pytest.mark.parametrize('change', ['reset_cap', 'closed', 'unclosed_prior', 'duplicate', 'unknown_version', 'escape', 'nonfinite'])
def test_invalid_phase_never_reaches_provider_configuration(launch, change):
    module, repo, notes, offline, output, budget = launch
    active = budget['phases'][-1]
    if change == 'reset_cap':
        active['limitUsd'] = '25'
    elif change == 'closed':
        active['status'] = 'closed_evaluated_no_promotion'
    elif change == 'unclosed_prior':
        budget['phases'][0]['status'] = 'running'
    elif change == 'duplicate':
        budget['phases'].append(dict(active))
    elif change == 'unknown_version':
        active['evaluationVersion'] = 'invented'
    elif change == 'escape':
        active['recordDirectory'] = '../outside'
    else:
        active['limitUsd'] = 'NaN'
    write(notes / 'live-budget.json', budget)
    with pytest.raises(ValueError):
        module.admit_launch(repo, notes, offline, output)
    assert not output.exists()


@pytest.mark.parametrize('target', ['source', 'report', 'active_output', 'offline', 'preregistration'])
def test_changed_authority_fails_before_any_launch(launch, target):
    module, repo, notes, offline, output, budget = launch
    if target == 'source':
        (repo / 'frozen.py').write_text('CHANGED = True\n')
    elif target == 'report':
        write(Path(budget['phases'][0]['output']) / 'report.json', {'rewritten': True})
    elif target == 'active_output':
        output = output.with_name('unregistered')
    elif target == 'preregistration':
        write(offline / 'evidence/reviewed-preregistration.json', {'manifestHash': 'unreviewed'})
    else:
        write(offline / 'verification-summary.json', {'sourceDrift': ['frozen.py']})
    with pytest.raises(ValueError):
        module.admit_launch(repo, notes, offline, output)
    assert not output.exists()


def test_circuit_counts_transport_failures_at_any_round_not_behavior_errors(tmp_path):
    module = load_launcher()
    for i in range(3):
        write(tmp_path / f'behavior-{i}' / 'receipt.json', {
            'errorCode': 'required_decision_failed', 'completedRound': 0,
            'errorDetails': {'lastErrorCode': 'invalid_actor_update'}})
    assert not module.provider_failure_stop(tmp_path)
    for i, code in enumerate(('policy_transport_failed', 'policy_usage_unavailable', 'policy_identity_mismatch')):
        write(tmp_path / f'transport-{i}' / 'receipt.json', {
            'errorCode': 'required_decision_failed', 'completedRound': i,
            'errorDetails': {'lastErrorCode': code}})
        assert module.provider_failure_stop(tmp_path) is (i == 2)


@pytest.mark.parametrize('change', ['v1_downgrade', 'missing_version', 'original_records', 'missing_records'])
def test_reviewed_phase_cannot_downgrade_or_overwrite_original_metadata(launch, change):
    module, repo, notes, offline, output, budget = launch
    active = budget['phases'][-1]
    if change == 'v1_downgrade':
        active['evaluationVersion'] = 'm5-behavior/v1'
    elif change == 'missing_version':
        active.pop('evaluationVersion')
    elif change == 'original_records':
        active['recordDirectory'] = '.'
    else:
        active.pop('recordDirectory')
    write(notes / 'live-budget.json', budget)
    with pytest.raises(ValueError):
        module.admit_launch(repo, notes, offline, output)


def test_v2_live_preregistration_and_opening_reservations_without_dispatch():
    import sys
    from decimal import Decimal
    import httpx
    from openai import OpenAI
    from app.services.world_simulation.evaluation import preregister, _verify_mask_hook
    from app.services.world_simulation.contracts import initial_snapshot, canonical_json
    from app.services.world_simulation.observations import build_observation
    from app.services.world_simulation.policy import StrictHTTPPolicy

    root = Path(__file__).resolve().parents[2]
    phase = root / 'docs/handoff/reflexive-world-simulation/behavior-rerun/public-grammar'
    config = json.loads((phase / 'preflight.json').read_text())
    pricing = json.loads((phase / config['policyFile']).read_text())
    manifest = preregister(pricing, max_usd=config['maxUsd'], evaluation_version=config['evaluationVersion'])
    assert len(manifest['cases']) == 36
    assert Decimal(manifest['allocatedUsd']) <= Decimal(config['maxUsd'])
    _verify_mask_hook(manifest['cases'])
    sent = []

    def forbidden(request):
        sent.append(request)
        raise AssertionError('Preregistration must not dispatch')

    with httpx.Client(transport=httpx.MockTransport(forbidden), trust_env=False) as http:
        with OpenAI(api_key='offline-fixture-only', base_url=pricing['policy']['baseUrl'], http_client=http) as sdk:
            for case in manifest['cases']:
                spec = case['spec']
                adapter = StrictHTTPPolicy(spec, client=sdk)
                try:
                    state = initial_snapshot(spec)
                    quotes = [adapter.reservation(build_observation(spec, state, actor['actorId'], 1))
                              for actor in spec['actors']]
                    # The two largest opening quotes fit before any measured
                    # usage releases allowance. Later calls still use store admission.
                    costs = sorted((Decimal(q['costUsd']) for q in quotes), reverse=True)
                    assert sum(costs[:spec['limits']['maxConcurrentCalls']]) <= Decimal(spec['limits']['maxCostUsd'])
                finally:
                    adapter.close()
    assert sent == []
    evidence = sys.modules['main_offline_guard'].root
    (evidence / 'reviewed-preregistration.json').write_text(canonical_json(manifest) + '\n')


def test_phase_record_conflict_preserves_both_files_and_identical_repeat_is_readonly(tmp_path):
    module = load_launcher()
    location = {'output': 'new-phase', 'manifestHash': 'frozen'}
    binding = {'manifestHash': 'frozen', 'policyId': 'fixture'}
    records = tmp_path / 'records'
    module.persist_phase_records(records, location, binding)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in records.iterdir()}
    module.persist_phase_records(records, dict(location), dict(binding))
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in records.iterdir()}
    with pytest.raises(ValueError, match='conflicts'):
        module.persist_phase_records(records, {'output': 'other'}, binding)
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in records.iterdir()}


def test_conflicting_binding_cannot_write_first_location(tmp_path):
    module = load_launcher()
    records = tmp_path / 'records'
    write(records / 'live-launch-binding.json', {'manifestHash': 'earlier'})
    with pytest.raises(ValueError, match='conflicts'):
        module.persist_phase_records(records, {'output': 'new'}, {'manifestHash': 'new'})
    assert not (records / 'live-evaluation-location.json').exists()


def test_explicit_additional_authorization_keeps_all_prior_consumption(launch):
    module, repo, notes, offline, output, budget = launch
    budget['authorizedUsd'] = '40'
    budget['phases'][-1]['limitUsd'] = '20'
    write(notes / 'live-budget.json', budget)
    with pytest.raises(ValueError):
        module.admit_launch(repo, notes, offline, output)
    authorization = {'schemaVersion': 'world-evaluation-authorization/v1', 'originalAuthorizedUsd': '25',
                     'totalAuthorizedUsd': '40', 'amendments': [
                         {'previousTotalUsd': '25', 'additionalUsd': '15', 'newTotalUsd': '40',
                          'confirmedUtc': '2026-10-17T14:25:00Z', 'userReply': 'Raise total ceiling to $40',
                          'scope': 'Diagnostic and full release study, all prior exposure counted.'}]}
    write(notes / 'evaluation-budget-authorization.json', authorization)
    assert module.admit_launch(repo, notes, offline, output)['maximum'] == '20'
    budget['phases'][-1]['limitUsd'] = '31'
    write(notes / 'live-budget.json', budget)
    with pytest.raises(ValueError):
        module.admit_launch(repo, notes, offline, output)
    budget['phases'][-1]['limitUsd'] = '20'
    write(notes / 'live-budget.json', budget)
    authorization['amendments'][0]['additionalUsd'] = '16'
    write(notes / 'evaluation-budget-authorization.json', authorization)
    with pytest.raises(ValueError):
        module.admit_launch(repo, notes, offline, output)
