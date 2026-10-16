#!/usr/bin/env python3
"""Run only the explicitly approved frozen synthetic evaluation, with existing credentials.

Credentials are read in-process from the existing primary checkout configuration;
they never appear in arguments, artifacts or output. Reuse the recorded active
phase directory. A versioned repair phase requires closed-phase accounting in
live-budget.json and can spend only the original authorization's remainder.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from decimal import Decimal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    notes = Path(__file__).resolve().parent
    approval = json.loads((notes / 'implementation-approval.json').read_text())
    if approval.get('live_evaluation_max_usd') != '25.00':
        raise ValueError('Expected explicit US$25 approval record')
    completed = json.loads((args.offline_run / 'evidence/completed.json').read_text())
    verified = json.loads((args.offline_run / 'verification-summary.json').read_text())
    if completed['exit_code'] != 0 or not completed['shutdown_complete'] or verified['sourceDrift']:
        raise ValueError('Offline release gate is incomplete')
    frozen = json.loads((args.offline_run / 'source-manifest.json').read_text())
    for name, expected in frozen.items():
        if hashlib.sha256((repository / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Source changed after offline acceptance: ' + name)
    location = notes / 'live-evaluation-location.json'
    destination = str(args.output.resolve())
    total_budget = notes / 'live-budget.json'
    maximum = '25'
    if total_budget.exists():
        budget = json.loads(total_budget.read_text())
        if destination != budget['activeOutput']:
            raise ValueError('Only the recorded active evaluation phase may dispatch')
        active = next(phase for phase in budget['phases'] if phase['output'] == destination)
        maximum = active['limitUsd']
        consumed = Decimal(0)
        for phase in budget['phases']:
            if phase['output'] == destination:
                continue
            report_path = Path(phase['output']) / 'report.json'
            if hashlib.sha256(report_path.read_bytes()).hexdigest() != phase['reportSha256']:
                raise ValueError('Prior phase budget evidence changed')
            consumed += Decimal(phase['settledCeilingUsd'])
        if consumed + Decimal(maximum) > Decimal('25'):
            raise ValueError('Combined evaluation phases exceed original approval')
    elif location.exists() and json.loads(location.read_text())['output'] != destination:
        raise ValueError('Reuse the original approved evaluation directory; do not reset its budget')
    location.write_text(json.dumps({'output': destination, 'maxCostUsd': maximum,
        'offlineRun': str(args.offline_run.resolve())}, indent=2) + '\n')

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
    from app.services.world_simulation.evaluation import preregister, run_evaluation
    from app.services.world_simulation.policy import StrictHTTPPolicy
    from app.services.world_simulation.contracts import WorldError
    pricing = json.loads((notes / 'live-policy.json').read_text())
    manifest = preregister(pricing, max_usd=maximum)
    pricing['authorization'] = {'pricingVerified': True, 'offlineGatesPassed': True,
        'manifestHash': manifest['manifestHash'], 'coordinator': 'Codex implementation coordinator',
        'evidenceRefs': [str(args.offline_run.resolve()), str(notes / 'live-policy-sources.json'),
                         str(notes / 'implementation-approval.json')]}
    (notes / 'live-launch-binding.json').write_text(json.dumps({
        'manifestHash': manifest['manifestHash'], 'sourceHashes': manifest['sourceHashes'],
        'allocatedUsd': manifest['allocatedUsd'], 'policyId': pricing['policyId'],
        'output': destination, 'authorization': pricing['authorization']}, indent=2) + '\n')

    def factory(spec):
        # Repeated transport failures do not justify dispatching the rest of the
        # matrix. Preserve its incomplete denominator and consumed exposure.
        receipts = [json.loads(p.read_text()) for p in args.output.glob('*/receipt.json')]
        if sum(r.get('errorCode') == 'required_decision_failed' and not r.get('completedRound')
               for r in receipts) >= 3:
            raise WorldError('provider_failure_stop', 'Repeated initial policy failures stopped new dispatches')
        print(json.dumps({'starting': spec['simulationId'],
                          'arm': 'ablation' if 'evaluationObservationMask' in spec else 'reflexive'}), flush=True)
        return StrictHTTPPolicy(spec)
    factory.evaluation_mode = 'external'
    report = run_evaluation(args.output.resolve(), factory, pricing, max_usd=maximum)
    print(json.dumps({'manifestHash': report['manifestHash'], 'cases': report['cases'],
        'budget': report['budget'], 'rubricGate': report['rubricGate'],
        'contrastGate': report['contrastGate']}), flush=True)


if __name__ == '__main__':
    main()
