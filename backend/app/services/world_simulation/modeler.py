"""Bounded research-to-model producer with durable, nonrenewable call allowance."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path

from .artifacts import atomic_json, read_json
from .compiler import build_compiler_messages
from .contracts import clone, decimal, digest, quantity, require


def _source_hash(value):
    # Legacy source bundles have coverage floats. They are opaque evidence here,
    # not world quantities, and use the legacy JSON representation for identity.
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def generate_candidate(directory: Path, *, research_report, research_generation_id, research_engine,
                       actor_bundle, ontology, simulation_requirement, policy_spec, transport=None):
    """Return a model proposal and conservative prep charges, never seal the model.

    The caller compiles and validates all proposed mechanisms before admission.
    Unknown request outcomes consume their full allowance on ordinary resume.
    """
    import fcntl
    from .policy import StrictHTTPModeler
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    require(isinstance(policy_spec, dict) and isinstance(policy_spec.get('limits'), dict),
            'missing_modeling_policy', 'World modeling needs an explicit HTTP policy and total run budget')
    policy_spec = clone(policy_spec)
    budget = policy_spec['limits']
    max_tokens = budget.get('maxTokens')
    max_cost = decimal(budget.get('maxCostUsd'), nonnegative=True)
    require(type(max_tokens) is int and max_tokens > 0 and max_cost > 0,
            'invalid_modeling_budget', 'World modeling requires a positive total token and USD ceiling')
    messages = build_compiler_messages(research_report=research_report,
        research_generation_id=research_generation_id, research_engine=research_engine,
        actor_bundle=actor_bundle, ontology=ontology, simulation_requirement=simulation_requirement)
    binding = digest({'messagesSha256': _source_hash(messages), 'policySpec': policy_spec})
    fd = os.open(directory / 'world_modeling.lock', os.O_RDWR | os.O_CREAT, 0o600)
    owned = transport is None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            from .contracts import WorldError
            raise WorldError('modeling_running', 'This modeling attempt is already active') from None
        path = directory / 'world_modeling_receipts.json'
        ledger = read_json(path) if path.exists() else {
            'schemaVersion': 'world-modeling-receipts/v1', 'binding': binding, 'attempts': [], 'candidate': None}
        require(ledger.get('schemaVersion') == 'world-modeling-receipts/v1' and ledger.get('binding') == binding,
                'modeling_binding_mismatch', 'Modeling inputs changed; create a new simulation attempt')

        def charged():
            records = [a.get('usage') or a['reservation'] for a in ledger['attempts']]
            return {'tokens': sum(a['tokens'] for a in records),
                    'costUsd': quantity(sum((decimal(a['costUsd']) for a in records), Decimal(0)))}

        while ledger['candidate'] is None:
            require(len(ledger['attempts']) < 2, 'modeling_attempts_exhausted',
                    'Modeling exhausted its durable two-request allowance')
            if transport is None:
                transport = StrictHTTPModeler(policy_spec)
            reserve = transport.reservation(clone(messages))
            used = charged()
            require(type(reserve.get('tokens')) is int and reserve['tokens'] > 0
                    and decimal(reserve.get('costUsd'), nonnegative=True) > 0,
                    'unbounded_transport', 'Modeling transport must reserve the complete request bound')
            require(used['tokens'] + reserve['tokens'] <= max_tokens
                    and decimal(used['costUsd']) + decimal(reserve['costUsd']) <= max_cost,
                    'modeling_budget_exhausted', 'Modeling dispatch would exceed the total run budget')
            row = {'number': len(ledger['attempts']) + 1, 'reservation': reserve, 'status': 'unknown', 'usage': None}
            ledger['attempts'].append(row)
            atomic_json(path, ledger, preserve_unicode=True)  # durable before the actual external request
            try:
                response = transport.decide(clone(messages))
                usage, candidate = response.usage, response.decision
                require(isinstance(candidate, dict), 'invalid_modeling_response', 'Modeler must return one JSON object')
                require(type(usage.get('tokens')) is int and 0 <= usage['tokens'] <= reserve['tokens']
                        and Decimal(0) <= decimal(usage.get('costUsd')) <= decimal(reserve['costUsd']),
                        'reservation_exceeded', 'Modeler usage exceeded its declared request bound')
            except Exception as error:
                usage = getattr(error, 'usage', None)
                if isinstance(usage, dict) and type(usage.get('tokens')) is int and 0 <= usage['tokens'] <= reserve['tokens']:
                    if Decimal(0) <= decimal(usage.get('costUsd')) <= decimal(reserve['costUsd']):
                        row.update(status='failed', usage=usage)
                atomic_json(path, ledger, preserve_unicode=True)
                continue
            row.update(status='succeeded', usage=usage)
            ledger['candidate'] = candidate
            atomic_json(path, ledger, preserve_unicode=True)
        used = charged()
        raw = clone(ledger['candidate'])
        effect = policy_spec.get('forecastEffect', 'diagnostic_only')
        require(effect in {'diagnostic_only', 'no_update'}, 'unsupported_policy', 'Unknown pinned forecast policy')
        raw['forecastEffect'] = effect
        # Provider/budget authority comes from the caller, never model output.
        raw['policy'] = clone(policy_spec['policy'])
        raw['limits'] = clone(budget)
        raw['limits']['maxTokens'] = max_tokens - used['tokens']
        raw['limits']['maxCostUsd'] = quantity(max_cost - decimal(used['costUsd']))
        require(raw['limits']['maxTokens'] > 0 and decimal(raw['limits']['maxCostUsd']) > 0,
                'modeling_budget_exhausted', 'No run budget remains after model preparation')
        receipt = {'binding': binding, 'used': used, 'totalBudget': {'tokens': max_tokens, 'costUsd': quantity(max_cost)},
                   'receiptSha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        atomic_json(directory / 'world_modeling_candidate.json', {'world_spec': raw, 'preparation': receipt}, preserve_unicode=True)
        return raw, receipt
    finally:
        os.close(fd)
        if owned and transport is not None:
            transport.close()
