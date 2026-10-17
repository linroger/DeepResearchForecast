"""Actor-bound information projections, independent of transport and persistence."""
from __future__ import annotations

from .contracts import (
    actors_by_id, clone, digest, parse_time, period_for, require,
    templates_by_id, visible_to,
)


def _eligible_inbox(spec: dict, snapshot: dict, actor_id: str, round_index: int) -> list[dict]:
    now = parse_time(period_for(spec, round_index)['start'])
    inbox = []
    for item in snapshot.get('interactions', {}).values():
        if (item.get('status') != 'pending' or actor_id not in item.get('recipientIds', [])
                or not visible_to(item, actor_id)
                or parse_time(item['deliverAt']) > now
                or parse_time(item['expiresAt']) <= now
                or actor_id in item.get('acceptedBy', [])):
            continue
        inbox.append(item)
    if spec.get('interactionQueuePolicy') == 'presented-v1':
        presented = snapshot.get('interactionQueueState', {}).get(actor_id, {})
        inbox.sort(key=lambda item: (presented.get(item['interactionId'], 0), item['deliverAt'], item['interactionId']))
    else:
        inbox.sort(key=lambda item: (item.get('lastResponseRound', 0), item['deliverAt'], item['interactionId']))
    return inbox


def delivered_inbox(spec: dict, snapshot: dict, actor_id: str, round_index: int) -> list[dict]:
    return clone(_eligible_inbox(spec, snapshot, actor_id, round_index)[:spec['limits']['maxInboxItems']])


def response_actors(spec: dict, snapshot: dict, round_index: int) -> list[str]:
    return sorted(actor['actorId'] for actor in spec['actors']
                  if actor['respondToOffers'] and delivered_inbox(spec, snapshot, actor['actorId'], round_index))


def build_observation(spec: dict, snapshot: dict, actor_id: str, round_index: int,
                      phase: str = 'proposal') -> dict:
    require(phase in {'proposal', 'response'}, 'invalid_phase', 'Unknown decision phase')
    actor = actors_by_id(spec).get(actor_id)
    require(actor is not None, 'unknown_actor', 'Actor is not admitted')
    period = period_for(spec, round_index)
    templates = templates_by_id(spec)
    inbox = delivered_inbox(spec, snapshot, actor_id, round_index)
    options = {}
    if phase == 'proposal':
        for tid in actor['capabilities']:
            template = templates[tid]
            if actor_id not in template['actorIds']:
                continue
            operations = ['propose', 'withdraw'] if template['kind'] == 'agreement' else ['execute']
            options[tid] = _option(template, operations)
    else:
        for item in inbox:
            template = templates[item['templateId']]
            if template['kind'] == 'agreement':
                options[template['templateId']] = _option(template, ['accept', 'reject', 'counter', 'defer'])
    # Only allowlisted fields are serialized. Modeler briefs, hidden counts,
    # global hashes, mechanism coefficients and rival feasibility stay outside.
    model = {key: clone(actor.get(key, [])) for key in (
        'objectives', 'values', 'incentives', 'constraints', 'beliefs', 'priorityRules')}
    model.update(actorId=actor_id, name=actor['name'])
    private = clone(snapshot['actorStates'][actor_id])
    world = {}
    for section in ('accounts', 'metrics', 'rules', 'relations', 'commitments'):
        world[section] = {key: clone(record) for key, record in snapshot.get(section, {}).items()
                          if visible_to(record, actor_id)}
    own_offers = [clone(item) for item in snapshot.get('interactions', {}).values()
                  if item.get('proposerId') == actor_id and visible_to(item, actor_id)]
    now = parse_time(period['start'])
    messages = [clone(item) for item in snapshot.get('interactions', {}).values()
                if item.get('kind') == 'message' and visible_to(item, actor_id)
                and parse_time(item['deliverAt']) <= now
                and parse_time(item['expiresAt']) > now]
    messages.sort(key=lambda item: (item['deliverAt'], item['interactionId']))
    result = {
        'schemaVersion': 'actor-world-observation/v1', 'actorId': actor_id,
        'round': round_index, 'phase': phase, 'simulatedAt': period['start'],
        'periodEnd': period['end'], 'horizon': spec['horizon'],
        'actor': model, 'privateState': private, 'world': world,
        'inbox': inbox, 'messages': messages[-spec['limits']['maxInboxItems']:],
        'ownOffers': sorted(own_offers, key=lambda item: item['interactionId']),
        'options': sorted(options.values(), key=lambda item: item['templateId']),
    }
    if 'evaluationObservationMask' in spec:
        from .evaluation import apply_observation_mask
        result = apply_observation_mask(spec, result)
    result['observationId'] = digest(result)
    return result


def _option(template: dict, operations: list[str]) -> dict:
    return {'templateId': template['templateId'], 'kind': template['kind'],
            'description': template['description'], 'inputs': clone(template['inputs']),
            'operations': operations}
