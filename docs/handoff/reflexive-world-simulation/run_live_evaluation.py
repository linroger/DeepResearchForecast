#!/usr/bin/env python3
"""Run only the explicitly approved frozen synthetic evaluation, with existing credentials.

Credentials are read in-process from the existing primary checkout configuration;
they never appear in arguments, artifacts or output. Reuse the recorded active
phase directory. A versioned repair phase requires closed-phase accounting in
live-budget.json and can spend only the recorded authorization's remainder.
Explicit human amendments retain all earlier exposure; they never reset it.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from decimal import Decimal, InvalidOperation


def authorized_ceiling(notes):
    """Preserve the original approval and require recorded human amendments."""
    total = Decimal('25')
    path = notes / 'evaluation-budget-authorization.json'
    if not path.exists():
        return total
    if path.is_symlink():
        raise ValueError('Budget authorization must be a local recorded document')
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or value.get('schemaVersion') != 'world-evaluation-authorization/v1'
            or value.get('originalAuthorizedUsd') != '25' or not isinstance(value.get('amendments'), list)):
        raise ValueError('Invalid evaluation authorization record')
    def amount(raw):
        if not isinstance(raw, str):
            raise ValueError('Authorization amounts must be decimal strings')
        try:
            parsed = Decimal(raw)
        except InvalidOperation:
            raise ValueError('Authorization amounts must be decimal strings') from None
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError('Authorization amounts must be positive and finite')
        return parsed
    for amendment in value['amendments']:
        if (not isinstance(amendment, dict) or amount(amendment.get('previousTotalUsd')) != total
                or not all(isinstance(amendment.get(key), str) and amendment[key].strip()
                           for key in ('confirmedUtc', 'userReply', 'scope'))):
            raise ValueError('Budget amendment must bind the previous authorization and human confirmation')
        total += amount(amendment.get('additionalUsd'))
        if amount(amendment.get('newTotalUsd')) != total:
            raise ValueError('Budget amendment arithmetic does not reconcile')
    if amount(value.get('totalAuthorizedUsd')) != total:
        raise ValueError('Total budget authorization does not reconcile')
    return total


def admit_launch(repository, notes, offline_run, output):
    """Read-only admission against the global ledger and exact offline snapshot."""
    approval = json.loads((notes / 'implementation-approval.json').read_text())
    if approval.get('live_evaluation_max_usd') != '25.00':
        raise ValueError('Expected explicit US$25 approval record')
    completed = json.loads((offline_run / 'evidence/completed.json').read_text())
    verified = json.loads((offline_run / 'verification-summary.json').read_text())
    if completed['exit_code'] != 0 or not completed['shutdown_complete'] or verified['sourceDrift']:
        raise ValueError('Offline release gate is incomplete')
    frozen = json.loads((offline_run / 'source-manifest.json').read_text())
    if not frozen:
        raise ValueError('Offline source manifest is empty')
    for name, expected in frozen.items():
        if hashlib.sha256((repository / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Source changed after offline acceptance: ' + name)
    destination = str(output.resolve())
    budget = json.loads((notes / 'live-budget.json').read_text())
    authorized = authorized_ceiling(notes)
    if str(authorized) != budget.get('authorizedUsd') or destination != budget.get('activeOutput'):
        raise ValueError('Only the recorded active evaluation phase may dispatch')
    phases = [phase for phase in budget['phases'] if phase['output'] == destination]
    if len(phases) != 1 or not phases[0]['status'].startswith('authorized_after_'):
        raise ValueError('Active phase must have a unique explicit offline-gate authorization')
    active = phases[0]
    maximum = Decimal(active['limitUsd'])
    if not maximum.is_finite() or maximum <= 0:
        raise ValueError('Active phase allocation must be positive and finite')
    consumed = Decimal(0)
    for phase in budget['phases']:
        if phase is active:
            continue
        if not phase['status'].startswith('closed_'):
            raise ValueError('Prior phases must be closed before another allocation')
        report_path = Path(phase['output']) / 'report.json'
        if hashlib.sha256(report_path.read_bytes()).hexdigest() != phase['reportSha256']:
            raise ValueError('Prior phase budget evidence changed')
        ceiling = Decimal(phase['settledCeilingUsd'])
        if not ceiling.is_finite() or ceiling < 0:
            raise ValueError('Prior phase exposure must be finite and nonnegative')
        consumed += ceiling
    if consumed + maximum > authorized:
        raise ValueError('Combined evaluation phases exceed recorded total approval')
    version = active.get('evaluationVersion')
    if version not in {'m5-behavior/v1', 'm5-behavior/v2', 'world-consistency-replay/v1'}:
        raise ValueError('Unknown evaluation version')
    preflight_name = ('reviewed-consistency-preregistration.json' if version == 'world-consistency-replay/v1'
                      else 'reviewed-preregistration.json')
    preflight = json.loads((offline_run / 'evidence' / preflight_name).read_text())
    expected_manifest = active.get('manifestHash')
    if (not expected_manifest or preflight.get('manifestHash') != expected_manifest
            or preflight.get('schemaVersion') != version):
        raise ValueError('Phase version and identity must bind its reviewed offline preregistration')
    def local_path(value):
        relative = Path(value)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Phase metadata must stay inside its handoff directory')
        path = notes / relative
        if not path.resolve().is_relative_to(notes.resolve()):
            raise ValueError('Phase metadata cannot escape through a symlink')
        return path
    record_name = active.get('recordDirectory')
    if not isinstance(record_name, str) or not record_name:
        raise ValueError('A phase-specific record directory is required')
    records = local_path(record_name)
    if records.resolve() == notes.resolve():
        raise ValueError('Phase records cannot overwrite original metadata')
    return {'destination': destination, 'maximum': str(maximum), 'version': version,
            'manifestHash': expected_manifest,
            'pricingPath': local_path(active.get('policyFile', 'live-policy.json')),
            'recordDirectory': records}


def build_phase_records(manifest, admitted, pricing, offline_run):
    """Build the shared launch records before any policy factory may dispatch."""
    return (
        {'output': admitted['destination'], 'maxCostUsd': admitted['maximum'],
         'evaluationVersion': admitted['version'], 'manifestHash': manifest['manifestHash'],
         'offlineRun': str(offline_run.resolve())},
        {'manifestHash': manifest['manifestHash'], 'sourceHashes': manifest['sourceHashes'],
         'allocatedUsd': manifest['allocatedUsd'], 'policyId': pricing['policyId'],
         'output': admitted['destination'], 'authorization': pricing['authorization']},
    )


def persist_phase_records(records, location, binding):
    """Preserve original/other phase metadata; repeated identical records are safe."""
    payloads = {'live-evaluation-location.json': location, 'live-launch-binding.json': binding}
    for name, value in payloads.items():
        path = records / name
        if path.is_symlink() or (path.exists() and json.loads(path.read_text()) != value):
            raise ValueError('Existing phase metadata conflicts with admitted launch')
    from app.services.world_simulation.artifacts import atomic_json
    for name, value in payloads.items():
        path = records / name
        if not path.exists():
            atomic_json(path, value)


def provider_failure_stop(output):
    """Stop new cases after three terminal transport/metering failures or capacity refusals."""
    failures = {'policy_transport_failed', 'policy_usage_unavailable', 'policy_identity_mismatch'}
    # A capacity refusal (HTTP 429 / throttle code, or a full shared model-call lease) stops a
    # world case directly once its waits run out, and ends a directed row's single request.
    refusals = {'provider_throttled', 'model_capacity_unavailable'}
    receipts = [json.loads(p.read_text()) for p in output.glob('*/receipt.json')]
    count = sum((r.get('errorCode') == 'required_decision_failed'
                 and r.get('errorDetails', {}).get('lastErrorCode') in failures)
                or r.get('errorCode') in refusals for r in receipts)
    journal_path = output / 'journal.json'
    if journal_path.exists():
        rows = json.loads(journal_path.read_text())['cases']
        if not isinstance(rows, dict):
            raise ValueError('Directed transport journal must contain case records')
        count += sum(row.get('status') in {'failed', 'unknown'} and row.get('errorCode') in failures | refusals
                     for row in rows.values())
    return count >= 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    notes = Path(__file__).resolve().parent
    admitted = admit_launch(repository, notes, args.offline_run, args.output)
    maximum = admitted['maximum']
    version, records = admitted['version'], admitted['recordDirectory']
    # Explicitly prevent app recovery hooks. This marker is not a network guard;
    # real HTTP requests below are authorized only for the frozen synthetic matrix.
    os.environ['DRF_TEST_PROCESS'] = '1'
    from dotenv import dotenv_values
    config = {}
    primary = Path('/Users/rogerlin/Downloads/DeepResearchForecast')
    for path in (primary / '.env', primary / 'backend/.env'):
        if path.is_file():
            config.update(dotenv_values(path))
    for key in ('LLM_PROVIDER', 'LLM_BASE_URL', 'LLM_MODEL_NAME', 'LLM_API_KEY'):
        if not config.get(key):
            raise ValueError('Existing HTTP configuration is incomplete')
        os.environ[key] = config[key]
    del config
    sys.path.insert(0, str(repository / 'backend'))
    if version == 'world-consistency-replay/v1':
        from app.services.world_simulation.consistency_evaluation import preregister, run_evaluation
    else:
        from app.services.world_simulation.evaluation import preregister, run_evaluation
    from app.services.world_simulation.policy import StrictHTTPPolicy
    from app.services.world_simulation.contracts import WorldError
    pricing = json.loads(admitted['pricingPath'].read_text())
    manifest = preregister(pricing, max_usd=maximum, evaluation_version=version)
    if manifest['manifestHash'] != admitted['manifestHash']:
        raise ValueError('Live preregistration differs from the reviewed offline proposal')
    pricing['authorization'] = {'pricingVerified': True, 'offlineGatesPassed': True,
        'manifestHash': manifest['manifestHash'], 'coordinator': 'Codex implementation coordinator',
        'evidenceRefs': [str(args.offline_run.resolve()), str(notes / 'live-policy-sources.json'),
                         str(notes / 'implementation-approval.json'), str(records / 'pricing-verification.json')]}
    persist_phase_records(records, *build_phase_records(manifest, admitted, pricing, args.offline_run))

    def factory(spec):
        # Repeated transport failures do not justify dispatching the rest of the
        # matrix. Preserve its incomplete denominator and consumed exposure.
        if provider_failure_stop(args.output):
            raise WorldError('provider_failure_stop', 'Repeated transport or metering failures stopped new dispatches')
        print(json.dumps({'starting': spec['simulationId'],
                          'arm': 'ablation' if 'evaluationObservationMask' in spec else 'reflexive'}), flush=True)
        return StrictHTTPPolicy(spec)
    factory.evaluation_mode = 'external'
    report = run_evaluation(args.output.resolve(), factory, pricing, max_usd=maximum, evaluation_version=version)
    print(json.dumps({'manifestHash': report['manifestHash'], 'cases': report['cases'],
        'budget': report['budget'], 'rubricGate': report.get('rubricGate'),
        'contrastGate': report.get('contrastGate'), 'diagnosticGate': report.get('diagnosticGate')}), flush=True)


if __name__ == '__main__':
    main()
