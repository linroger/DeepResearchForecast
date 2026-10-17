"""Synthetic, cross-domain mechanism examples; never empirical forecast inputs."""
from __future__ import annotations

from .contracts import add_days, clone, validate_spec

BASIS = {'kind': 'scenario_assumption', 'refs': ['synthetic-example/v1']}
PUBLIC = {'kind': 'public'}


def _actor(aid, name, goal):
    return {'actorId': aid, 'name': name, 'objectives': [goal], 'values': ['Honor explicit obligations'],
            'incentives': [goal], 'constraints': ['Spend only available authorized resources'],
            'beliefs': [], 'capabilities': ['communicate'], 'controlledAccounts': [],
            'evidenceGrade': 'scenario-assumption', 'basis': clone(BASIS)}


def _account(owner, amount, unit='currency', public=False):
    return {'ownerId': owner, 'unit': unit, 'balance': str(amount), 'basis': clone(BASIS),
            'visibility': clone(PUBLIC) if public or owner == 'external' else {'kind': 'actors', 'actorIds': [owner]}}


def _metric(value, unit='goods_per_day'):
    return {'kind': 'rate', 'value': str(value), 'unit': unit, 'visibility': clone(PUBLIC), 'basis': clone(BASIS)}


def _rule(value):
    return {'value': value, 'visibility': clone(PUBLIC), 'basis': clone(BASIS)}


def _template(tid, kind, actors, description, parameters, inputs=None):
    return {'templateId': tid, 'kind': kind, 'actorIds': actors, 'description': description,
            'parameters': parameters, 'inputs': inputs or {}, 'basis': clone(BASIS), 'visibility': clone(PUBLIC)}


def example_spec(domain='investment', *, simulation_id='sim_example', generation_id='example-v1',
                 periods=4, seed=0):
    start = '2030-01-01T00:00:00Z'
    spec = {'schemaVersion': 'simulation-world-spec/v1', 'engine': 'world-v1',
            'simulationId': simulation_id, 'generationId': generation_id, 'seed': seed,
            'forecastEffect': 'diagnostic_only',
            'periods': [{'start': add_days(start, i), 'end': add_days(start, i + 1)} for i in range(periods)],
            'initialState': {'accounts': {}, 'metrics': {}, 'rules': {}, 'relations': {}},
            'actors': [], 'actionCatalog': [], 'assumptions': [
                {'assumptionId': 'synthetic-example/v1', 'description': 'All values and mechanisms are synthetic.',
                 'visibility': clone(PUBLIC)}],
            'scheduledEvents': [], 'flows': []}
    state = spec['initialState']
    if domain == 'investment':
        spec['actors'] = [_actor('producer', 'Producer', 'Expand capacity when affordable and fulfill orders'),
                          _actor('buyer', 'Buyer', 'Acquire supply as capacity becomes available'),
                          _actor('financier', 'Financier', 'Preserve liquidity and evaluate commitments'),
                          _actor('authority', 'Permitting institution', 'Maintain authorized safe production')]
        state['accounts'] = {'producer_cash': _account('producer', 10), 'capex_sink': _account('external', 0),
                             'buyer_cash': _account('buyer', 30), 'producer_stock': _account('producer', 4, 'goods'),
                             'buyer_stock': _account('buyer', 0, 'goods'),
                             'raw_supply': _account('external', 100, 'goods')}
        state['metrics'] = {'capacity': _metric(4), 'input_limit': _metric(7)}
        state['rules'] = {'permit': _rule(True)}
        spec['flows'] = [{'flowId': 'production', 'sourceAccount': 'raw_supply', 'targetAccount': 'producer_stock',
                          'rateMetric': 'capacity', 'limitMetric': 'input_limit',
                          'visibility': clone(PUBLIC), 'basis': clone(BASIS)}]
        spec['actionCatalog'] = [
            _template('expand', 'investment', ['producer'],
                      'Spend 6 currency to add 3 units/day of capacity after two days, subject to permit.',
                      {'fromAccount': 'producer_cash', 'toAccount': 'capex_sink', 'cost': '6',
                       'targetMetric': 'capacity', 'delta': '3', 'durationDays': '2', 'requiresRule': 'permit'}),
            _template('purchase', 'agreement', ['buyer'],
                      'Offer the producer a purchase of quantity goods for total price currency, delivered immediately after consent.',
                      {'recipientIds': ['producer'], 'durationDays': '0', 'transfers': [
                          {'fromAccount': 'producer_stock', 'toAccount': 'buyer_stock', 'amount': '$quantity'},
                          {'fromAccount': 'buyer_cash', 'toAccount': 'producer_cash', 'amount': '$price'}]},
                      {'quantity': {'type': 'decimal', 'min': '1', 'max': '10', 'required': True},
                       'price': {'type': 'decimal', 'min': '1', 'max': '20', 'required': True}}),
        ]
    elif domain == 'trade':
        spec['actors'] = [_actor('regulator', 'Regulator', 'Implement the declared route restriction'),
                          _actor('importer', 'Importer', 'Obtain goods through currently eligible routes'),
                          _actor('supplier_a', 'Supplier A', 'Sell available goods on route A'),
                          _actor('supplier_b', 'Supplier B', 'Sell available goods on route B')]
        state['accounts'] = {'importer_cash': _account('importer', 30), 'importer_stock': _account('importer', 0, 'goods'),
                             'supplier_a_cash': _account('supplier_a', 0), 'supplier_b_cash': _account('supplier_b', 0),
                             'supplier_a_stock': _account('supplier_a', 10, 'goods'),
                             'supplier_b_stock': _account('supplier_b', 10, 'goods')}
        state['rules'] = {'route_a_eligible': _rule(True), 'route_b_eligible': _rule(True)}
        spec['actionCatalog'] = [_template('restrict_a', 'policy', ['regulator'],
            'Make route A ineligible for new orders after two days; accepted orders are grandfathered.',
            {'ruleId': 'route_a_eligible', 'value': False, 'durationDays': '2', 'authorityIds': ['regulator']})]
        for route, cost in [('a', '2'), ('b', '3')]:
            supplier = 'supplier_' + route
            spec['actionCatalog'].append(_template('order_' + route, 'agreement', ['importer'],
                f'Offer {cost} currency for one good from {supplier}; requires route eligibility and supplier consent.',
                {'recipientIds': [supplier], 'durationDays': '0', 'requiresRule': f'route_{route}_eligible',
                 'transfers': [{'fromAccount': 'importer_cash', 'toAccount': supplier + '_cash', 'amount': cost},
                               {'fromAccount': supplier + '_stock', 'toAccount': 'importer_stock', 'amount': '1'}]}))
    elif domain == 'coalition':
        spec['actors'] = [_actor('org_a', 'Organization A', 'Build a coalition to pass the program'),
                          _actor('org_b', 'Organization B', 'Support the program after an explicit coalition agreement'),
                          _actor('org_c', 'Organization C', 'Preserve the institutional budget'),
                          _actor('institution', 'Executing institution', 'Execute only authorized and funded programs')]
        state['accounts'] = {'institution_budget': _account('institution', 80, public=True),
                             'program_sink': _account('external', 0)}
        state['rules'] = {'mandate': _rule(True), 'program_authorized': _rule(False)}
        state['relations'] = {'coalition_ab': {'value': 'none', 'visibility': clone(PUBLIC), 'basis': clone(BASIS)}}
        spec['actionCatalog'] = [
            _template('coalition', 'agreement', ['org_a'], 'Propose an explicit coalition to B; consent does not cast votes.',
                      {'recipientIds': ['org_b'], 'relationId': 'coalition_ab', 'relationValue': 'allied', 'durationDays': '0'}),
            _template('program_vote', 'vote', ['org_a', 'org_b', 'org_c'],
                      'Cast your own formal vote. Weights A/B/C are 45/30/25; passage requires 51 and funding of 60.',
                      {'motionId': 'program', 'weights': {'org_a': '45', 'org_b': '30', 'org_c': '25'},
                       'threshold': '51', 'fromAccount': 'institution_budget', 'toAccount': 'program_sink',
                       'cost': '60', 'targetRule': 'program_authorized', 'ruleValue': True, 'mandateRule': 'mandate'},
                      {'support': {'type': 'boolean', 'required': True}}),
        ]
    else:
        raise ValueError('Unknown synthetic domain')
    ids = [actor['actorId'] for actor in spec['actors']]
    spec['actionCatalog'].append(_template('communicate', 'message', ids, 'Make a nonbinding public statement.',
        {}, {'text': {'type': 'string', 'required': True}}))
    for actor in spec['actors']:
        actor['capabilities'] = [t['templateId'] for t in spec['actionCatalog'] if actor['actorId'] in t['actorIds']]
        actor['controlledAccounts'] = [key for key, account in state['accounts'].items() if account['ownerId'] == actor['actorId']]
    return validate_spec(spec)


class ExamplePolicy:
    """Deterministic workflow demonstration; never a substitute for model evaluation."""
    external = False

    def __init__(self, domain):
        self.domain = domain
        self.observations = []

    def decide(self, obs):
        self.observations.append(clone(obs))
        aid, world, round_index = obs['actorId'], obs['world'], obs['round']
        intents = []
        if obs['phase'] == 'response':
            for offer in obs['inbox'][:1]:
                intents.append({'templateId': offer['templateId'], 'operation': 'accept',
                                'interactionId': offer['interactionId'], 'termsVersion': offer['termsVersion']})
        elif self.domain == 'investment':
            if aid == 'producer' and round_index == 1:
                intents = [{'templateId': 'expand'}]
            if aid == 'buyer':
                quantity = '3' if world['metrics']['capacity']['value'] == '4' else '6'
                intents = [{'templateId': 'purchase', 'operation': 'propose',
                            'parameters': {'quantity': quantity, 'price': quantity}}]
        elif self.domain == 'trade':
            if aid == 'regulator' and round_index == 1:
                intents = [{'templateId': 'restrict_a'}]
            if aid == 'importer':
                route = 'a' if world['rules']['route_a_eligible']['value'] else 'b'
                intents = [{'templateId': 'order_' + route, 'operation': 'propose'}]
        elif self.domain == 'coalition':
            if aid == 'org_a' and round_index == 1:
                intents = [{'templateId': 'coalition', 'operation': 'propose'}]
            elif aid in {'org_a', 'org_b'} and world['relations']['coalition_ab']['value'] == 'allied':
                intents = [{'templateId': 'program_vote', 'parameters': {'support': True}}]
        return {'actorId': aid, 'observationId': obs['observationId'], 'intents': intents,
                'rationale': 'Synthetic policy follows visible constraints and declared objectives.'}
