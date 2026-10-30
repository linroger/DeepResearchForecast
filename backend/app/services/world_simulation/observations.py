"""Actor-bound information projections, independent of transport and persistence."""
from __future__ import annotations

from .contracts import (
    CAUSAL_ORDER_POLICY, actors_by_id, anchor_enabled, causal_order_key, clone, digest, parse_time, period_for, require,
    templates_by_id, visible_to,
)


def _interaction_order(spec: dict, snapshot: dict, item: dict) -> tuple:
    if spec.get('resolutionOrderPolicy') == CAUSAL_ORDER_POLICY:
        return causal_order_key(snapshot, item['interactionId'])
    return (item['interactionId'],)


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
        inbox.sort(key=lambda item: (presented.get(item['interactionId'], 0), item['deliverAt'],
                                     _interaction_order(spec, snapshot, item)))
    else:
        inbox.sort(key=lambda item: (item.get('lastResponseRound', 0), item['deliverAt'],
                                     _interaction_order(spec, snapshot, item)))
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
    if 'researchContext' in spec:
        context = spec['researchContext']
        require(context.get('schemaVersion') == 'native-research-context/v1'
                and isinstance(context.get('actors', {}).get(actor_id), str),
                'invalid_preparation_context', 'Actor preparation projection is missing or invalid')
        model['researchContext'] = context['actors'][actor_id]
    private = clone(snapshot['actorStates'][actor_id])
    world = {}
    for section in ('accounts', 'metrics', 'rules', 'relations', 'commitments'):
        world[section] = {key: clone(record) for key, record in snapshot.get(section, {}).items()
                          if visible_to(record, actor_id)}
    for record in world['metrics'].values():
        if 'baseline' in record:
            # Internal seals bind the complete research generation, including
            # modeler-only material. Actors see the public measurement identity
            # rather than a fingerprint of private research they cannot access.
            record['baseline'].pop('preparationSha256', None)
            record['baseline'].pop('researchGenerationId', None)
            for ref in record.get('basis', {}).get('refs', []):
                if isinstance(ref, dict):
                    ref.pop('bundleSha256', None)
            # The kernel can evolve value while retaining its immutable source
            # measurement. Do not relabel that result as a fresh observation.
            record['valueSemantics'] = {'kind': 'simulated_state', 'simulatedAt': period['start'],
                                        'baselineAppliesTo': 'initial_value'}
    own_offers = [clone(item) for item in snapshot.get('interactions', {}).values()
                  if item.get('proposerId') == actor_id and visible_to(item, actor_id)]
    now = parse_time(period['start'])
    messages = [clone(item) for item in snapshot.get('interactions', {}).values()
                if item.get('kind') == 'message' and visible_to(item, actor_id)
                and parse_time(item['deliverAt']) <= now
                and parse_time(item['expiresAt']) > now]
    messages.sort(key=lambda item: (item['deliverAt'], _interaction_order(spec, snapshot, item)))
    result = {
        'schemaVersion': 'actor-world-observation/v1', 'actorId': actor_id,
        'round': round_index, 'phase': phase, 'simulatedAt': period['start'],
        'periodEnd': period['end'], 'horizon': spec['horizon'],
        'actor': model, 'privateState': private, 'world': world,
        'inbox': inbox, 'messages': messages[-spec['limits']['maxInboxItems']:],
        'ownOffers': sorted(own_offers, key=lambda item: _interaction_order(spec, snapshot, item)),
        'options': sorted(options.values(), key=lambda item: item['templateId']),
    }
    if 'evaluationObservationMask' in spec:
        from .evaluation import apply_observation_mask
        result = apply_observation_mask(spec, result)
    if anchor_enabled(spec):
        result = _anchor_observation(spec, snapshot, result, actor_id, round_index)
    result['observationId'] = digest(result)
    return result


def _simulated_record(value):
    """Keep simulated protocol data, never an inherited initial evidence basis."""
    if not isinstance(value, dict):
        return clone(value)
    # Only these record-wrapper locations are server provenance. Actor-defined
    # terms and typed values are opaque protocol data; their legal keys may be
    # named description/basis/conditions/effects and must remain exact.
    result = {key: clone(item) for key, item in value.items()
              if key not in {"basis", "structuralBasis", "sourceBindings", "descriptionBasis",
                             "worldAnchor", "pack_hash", "input_hash", "preparedParametersHash"}}
    if isinstance(result.get("effects"), list):
        result["effects"] = [_simulated_record(effect) for effect in result["effects"]]
    if "basis" in value:
        result["basis"] = {"kind": "simulation_event", "refs": ["visible_" + digest(result)]}
    return result


def _anchor_observation(spec, snapshot, result, actor_id, round_index):
    """Final enabled-only allowlist across old and new actor request channels."""
    view = spec["worldAnchorObservations"]["actors"][actor_id]["periods"][str(round_index)]
    model = {"actorId": actor_id, "name": actors_by_id(spec)[actor_id]["name"],
             **{key: [] for key in ("objectives", "values", "incentives", "constraints", "beliefs", "priorityRules")},
             "anchorEvidence": clone(view["items"])}
    # A public statement remains attributed evidence, not a new sincere belief,
    # objective or behavioral priority. Modeler/legacy profiles never fill gaps.
    result["actor"] = model
    marker = snapshot.get("anchorObservationState")
    require(isinstance(marker, dict) and marker.get("schemaVersion") == "world-anchor-state/v1",
            "anchor_binding_mismatch", "Anchor observation origin state is missing")
    origins = marker["simulatedFields"]
    initial_fields = set(view["initialFields"])
    world = {key: {} for key in ("accounts", "metrics", "rules", "relations", "commitments")}
    structural = {"accounts": ("ownerId", "unit"), "metrics": ("kind", "unit"), "rules": (), "relations": ()}
    for section in structural:
        for record_id, record in result["world"][section].items():
            allowed = {}
            original = spec["initialState"][section][record_id]
            simulated = False
            for field in (("balance", "reserved") if section == "accounts" else ("value",)):
                origin = origins.get(section, {}).get(record_id, {}).get(field)
                if origin is not None:
                    require(type(origin.get("round")) is int and 1 <= origin["round"] <= snapshot["round"]
                            and parse_time(origin["at"]) <= parse_time(result["simulatedAt"]),
                            "anchor_binding_mismatch", "Anchor simulated origin is invalid")
                    allowed[field] = clone(record[field])
                    simulated = True
                elif (f"/initialState/{section}/{record_id}/{field}" in initial_fields
                      and type(record.get(field)) is type(original.get(field)) and record.get(field) == original.get(field)):
                    allowed[field] = clone(record[field])
                elif section == "accounts" and field == "reserved" and "balance" in allowed and record.get(field) == "0":
                    allowed[field] = "0"  # Native initial absence of reservations, not an assumed balance.
            if allowed:
                world[section][record_id] = {**{key: clone(record[key]) for key in structural[section]},
                    **allowed, "visibility": clone(record["visibility"]),
                    "evidenceType": "simulated" if simulated else record.get("evidenceType", "reported"),
                    "valueStatus": "specified"}
    for record_id, record in result["world"]["commitments"].items():
        if (snapshot["round"] >= 1 and isinstance(record.get("createdAt"), str)
                and parse_time(spec["asOf"]) <= parse_time(record["createdAt"]) <= parse_time(result["simulatedAt"])):
            world["commitments"][record_id] = _simulated_record(record)
    result["world"] = world

    old = result["privateState"]
    private = {"beliefs": [], "plans": [], "priorityChanges": [], "observedEvents": [],
               "lastObservedEvents": [], "lastActionResults": []}
    for field in ("beliefs", "plans"):
        for item in old.get(field, []):
            if (isinstance(item, dict) and item.get("round", 0) >= 1
                    and item.get("basis", {}).get("kind") == "simulation_event" and isinstance(item.get("text"), str)):
                private[field].append({key: clone(item[key]) for key in ("text", "round", "observationId", "decisionId") if key in item})
                private[field][-1]["evidenceType"] = "simulated"
    private["lastObservedEvents"] = [_simulated_record(item) for item in old.get("lastObservedEvents", [])
                                      if item.get("round", 0) >= 1 and visible_to(item, actor_id)]
    private["observedEvents"] = [item["eventId"] for item in private["lastObservedEvents"]]
    private["lastActionResults"] = [{key: clone(item[key]) for key in
        ("intentId", "actorId", "round", "accepted", "code", "explanation") if key in item}
        for item in old.get("lastActionResults", []) if item.get("round", 0) >= 1]
    result["privateState"] = private
    for field in ("inbox", "ownOffers", "messages"):
        result[field] = [_simulated_record(item) for item in result[field] if item.get("createdRound", 0) >= 1]
    options = []
    for option in result["options"]:
        approved = view["options"].get(option["templateId"])
        if approved is not None:
            options.append({**option, "description": approved["description"], "inputs": clone(approved["inputs"])})
    result["options"] = options
    return result


def _option(template: dict, operations: list[str]) -> dict:
    return {'templateId': template['templateId'], 'kind': template['kind'],
            'description': template['description'], 'inputs': clone(template['inputs']),
            'operations': operations}
