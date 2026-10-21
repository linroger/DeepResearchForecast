"""Real world-v1 producers/consumers; only external HTTP/model output is scripted."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from app.services.world_simulation.artifacts import atomic_json, file_digest, load_inputs, read_json
from app.services.world_simulation.compiler import build_compiler_messages
from app.services.world_simulation.contracts import (
    WorldError, add_days, canonical_json, digest, stable_id, validate_decision, validate_snapshot, validate_spec,
)
from app.services.world_simulation.controller import run_round
from app.services.world_simulation.examples import BASIS, ExamplePolicy, example_spec
from app.services.world_simulation.kernel import initialize_world, resolve_round, stage_interactions
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.policy import PolicyFailure, StrictHTTPPolicy
from app.services.world_simulation.results import load_frozen_result, read_result, report_context
from app.services.world_simulation.service import WorldSimulationService as Service, run_child
from app.services.world_simulation.store import WorldStore

pytestmark = pytest.mark.guarded_runner

PRIVATE_GOAL = "Preserve the confidential reserve for the unannounced acquisition"
PUBLIC_FACT = "Maintain deliveries under the published production schedule"
REPORT = "Producer and Buyer use the declared synthetic scenario. " + PUBLIC_FACT


def raw_case():
    raw = example_spec(periods=3)
    for key in ('simulationId', 'generationId'):
        raw.pop(key)
    producer = raw['actors'][0]
    producer['basis'] = {'kind': 'source_claim', 'refs': [{'actorId': 'producer', 'claimId': 'goals.0'}]}
    producer.pop('evidenceGrade')
    producer.pop('objectives')
    for field in ('values', 'incentives', 'constraints', 'beliefs'):
        producer[field] = [{'text': text, 'basis': deepcopy(BASIS)} for text in producer[field]]
    bundle = {'actors': [
        {'actor_id': 'producer', 'name': 'Producer', 'goals': [PRIVATE_GOAL]},
        {'actor_id': 'buyer', 'name': 'Buyer', 'claims': [{
            'claim_id': 'public_schedule', 'claim': PUBLIC_FACT, 'visibility': 'public',
            'evidence_type': 'actor_stated_claim', 'report_ref': {
                'start': REPORT.index(PUBLIC_FACT), 'end': len(REPORT),
                'sha256': hashlib.sha256(PUBLIC_FACT.encode()).hexdigest()}}]},
    ]}
    raw['policy'] = {
        'provider': 'openai', 'model': 'context-audit-fixture', 'baseUrl': 'https://fixture.invalid/v1',
        'timeoutSeconds': 17, 'maxInputTokens': 100000,
        'pricing': {
            'provider': 'openai', 'model': 'context-audit-fixture', 'baseUrl': 'https://fixture.invalid/v1',
            'inputUsdPerMillion': '2', 'outputUsdPerMillion': '9', 'contextWindowTokens': 120000,
            'maxOutputTokens': 2048, 'inputOverheadTokens': 256,
            'outputTokenParameter': 'max_completion_tokens', 'maxOutputIncludesReasoning': True,
            'source': {'reference': 'fixture://context-audit', 'asOf': '2026-10-21T00:00:00Z'}}}
    raw['limits'].update(maxOutputTokens=512, maxTokens=1000000, maxCostUsd='10')
    return raw, bundle


def prepare(root, raw=None, bundle=None, simulation_id='sim_context'):
    original, actors = raw_case()
    prepared = Service.prepare_model(simulation_id, root=root,
        raw_spec=original if raw is None else raw, actor_bundle=actors if bundle is None else bundle,
        research_report=REPORT, research_generation_id='research_context', research_engine='v3')
    return prepared, admit(root, simulation_id, prepared)


def admit(root, simulation_id, prepared):
    directory = root / simulation_id
    # The parent manager owns this wrapper. Supply the exact persisted admission
    # record it writes while keeping service/controller/store behavior real.
    atomic_json(directory / 'state.json', {'simulation_engine': 'world-v1',
        'world_generation_id': prepared['spec']['generationId'],
        'world_spec_sha256': file_digest(directory / 'world_spec.json'),
        'world_input_manifest_sha256': prepared['manifest_sha256']})
    return directory


def http_policy(spec, sent, choose=None, policy_type=StrictHTTPPolicy):
    import httpx
    from openai import OpenAI

    def dispatch(request):
        body = json.loads(request.content)
        observation = json.loads(body['messages'][1]['content'])
        sent.append(body)
        decision = choose(observation) if choose else {'intents': []}
        return httpx.Response(200, json={
            'id': 'fixture', 'object': 'chat.completion', 'created': 0, 'model': spec['policy']['model'],
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': json.dumps(decision)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140}})

    http = httpx.Client(transport=httpx.MockTransport(dispatch), follow_redirects=False, trust_env=False)
    sdk = OpenAI(api_key='synthetic-context-audit', base_url=spec['policy']['baseUrl'], http_client=http)
    return policy_type(spec, client=sdk), sdk


@pytest.mark.parametrize('channel', ['other_profile', 'other_name', 'public_rule', 'menu_description', 'menu_input',
                                    'public_effect', 'public_assumption'])
def test_private_actor_text_cannot_be_relabelled_as_an_assumption(tmp_path, channel):
    raw, bundle = raw_case()
    if channel == 'other_profile':
        raw['actors'][1]['objectives'] = [PRIVATE_GOAL]
    elif channel == 'other_name':
        raw['actors'][2]['name'] = PRIVATE_GOAL
    elif channel == 'public_rule':
        raw['initialState']['rules']['announcement'] = {
            'value': PRIVATE_GOAL, 'visibility': {'kind': 'public'}, 'basis': deepcopy(BASIS)}
    elif channel == 'menu_description':
        raw['actionCatalog'][-1]['description'] = PRIVATE_GOAL
    elif channel == 'menu_input':
        raw['actionCatalog'][-1]['inputs']['text']['enum'] = [PRIVATE_GOAL]
    elif channel == 'public_effect':
        raw['scheduledEvents'] = [{'eventId': 'announcement', 'kind': 'rule_set',
            'at': raw['periods'][0]['end'], 'parameters': {'ruleId': 'permit', 'value': PRIVATE_GOAL},
            'visibility': {'kind': 'public'}, 'basis': deepcopy(BASIS)}]
    else:
        raw['assumptions'].append({'assumptionId': 'leaked_context', 'description': PRIVATE_GOAL,
                                   'visibility': {'kind': 'public'}})
    try:
        prepared, directory = prepare(tmp_path, raw, bundle)
    except WorldError as error:
        assert error.code == 'forbidden_actor_evidence'
        assert not (tmp_path / 'sim_context/world_input_manifest.json').exists()
        return
    # A red must demonstrate the real downstream exposure, not just acceptance
    # by a helper. HTTP I/O is scripted; request construction remains real.
    sent = []
    policy, sdk = http_policy(prepared['spec'], sent)
    try:
        assert run_child(directory, policy=policy) == 0
    finally:
        policy.close()
        sdk.close()
    outsiders = [body for body in sent if json.loads(body['messages'][1]['content'])['actorId'] != 'producer']
    consumed = canonical_json(outsiders) + canonical_json(report_context(load_frozen_result(directory)))
    assert PRIVATE_GOAL not in consumed, f'{channel}: private research reached an unauthorized consumer'


def test_dossier_to_actual_actor_prompt_current_state_and_frozen_report(tmp_path, monkeypatch):
    from app.services.world_simulation import policy as policy_module

    raw, bundle = raw_case()
    modeler_sent, modeler_sdks = [], []
    real_modeler = policy_module.StrictHTTPModeler
    def modeler(spec):
        transport, sdk = http_policy(spec, modeler_sent, lambda payload: deepcopy(raw), policy_type=real_modeler)
        modeler_sdks.append(sdk)
        return transport
    monkeypatch.setattr(policy_module, 'StrictHTTPModeler', modeler)
    try:
        prepared = Service.prepare_model('sim_context', root=tmp_path, raw_spec=None,
            research_report=REPORT, research_generation_id='research_context', research_engine='v3',
            actor_bundle=bundle, ontology={'fixture': 'ontology-context'},
            simulation_requirement='Trace capacity through the declared horizon.',
            policy_spec={'policy': raw['policy'], 'limits': raw['limits']})
    finally:
        for sdk in modeler_sdks:
            sdk.close()
    directory = admit(tmp_path, 'sim_context', prepared)
    assert len(modeler_sent) == 1
    upstream = json.loads(modeler_sent[0]['messages'][1]['content'])
    assert upstream['report'] == REPORT and upstream['ontology']['fixture'] == 'ontology-context'
    assert upstream['requirement'] == 'Trace capacity through the declared horizon.'
    assert upstream['claims'][0]['claims'][0]['text'] == PRIVATE_GOAL
    assert prepared['spec']['sourceBindings']['reportSha256'] == hashlib.sha256(REPORT.encode()).hexdigest()
    assert prepared['spec']['actors'][0]['objectives'][0]['text'] == PRIVATE_GOAL
    scripted = ExamplePolicy('investment')
    sent = []
    def choose(observation):
        decision = scripted.decide(observation)
        return {key: value for key, value in decision.items() if key not in {'actorId', 'observationId'}}
    policy, sdk = http_policy(prepared['spec'], sent, choose)
    try:
        assert run_child(directory, policy=policy) == 0
    finally:
        policy.close()
        sdk.close()
    observations = [json.loads(body['messages'][1]['content']) for body in sent]
    for body in sent:
        actor_bytes = canonical_json(body['messages'])
        assert all(key not in actor_bytes for key in ('sourceBindings', 'research_context', 'generationId', 'seed'))
    producer = next(o for o in observations if o['actorId'] == 'producer' and o['round'] == 1)
    assert producer['actor']['objectives'][0]['text'] == PRIVATE_GOAL
    assert all(PRIVATE_GOAL not in canonical_json(o) for o in observations if o['actorId'] != 'producer')
    assert all(o['observationId'] == digest({k: v for k, v in o.items() if k != 'observationId'}) for o in observations)
    later = next(o for o in observations if o['actorId'] == 'producer' and o['round'] == 3 and o['phase'] == 'proposal')
    assert later['world']['metrics']['capacity']['value'] == '7'
    assert later['privateState']['lastActionResults'] and later['world']['commitments']
    result = Service.require_complete('sim_context', root=tmp_path)
    assert result['completed'] and result['round'] == result['committedRound'] == 3
    assert result['specHash'] == digest(prepared['spec'])
    assert PRIVATE_GOAL not in canonical_json(report_context(result))
    assert report_context(result)['probabilityEvidence'] is False
    assert read_result(directory, view='analyst')['sourceBindings'] == prepared['spec']['sourceBindings']
    with WorldStore(directory / 'world.sqlite3', prepared['spec'], read_only=True) as store:
        for obs in observations:
            assert store.observation(f"{obs['round']}:{obs['phase']}:{obs['actorId']}") == obs


def test_restart_reuses_exact_observation_and_saved_policy_fork_resets_world(tmp_path):
    prepared, directory = prepare(tmp_path)
    spec = prepared['spec']
    with WorldStore(directory / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('first_shift')
        run_round(store, ExamplePolicy('investment'), fence)
        before = store.head()
        store.release_writer(fence)
    assert before['round'] == 1 and before['metrics']['capacity']['value'] == '4'
    assert any(c['status'] == 'pending' for c in before['commitments'].values())
    resumed = ExamplePolicy('investment')
    assert run_child(directory, policy=resumed) == 0
    assert min(o['round'] for o in resumed.observations) == 2
    assert load_frozen_result(directory)['world']['metrics']['capacity']['value'] == '7'
    parent_bytes = {p.name: p.read_bytes() for p in directory.glob('*.json')}
    fork = Service.fork('sim_context', 'sim_fork', root=tmp_path, seed=19)
    assert fork['spec']['generationId'] != spec['generationId']
    assert fork['spec']['simulationId'] == 'sim_fork' and fork['spec']['seed'] == 19
    assert fork['spec']['sourceBindings'] == spec['sourceBindings']
    assert fork['spec']['policy'] == spec['policy']
    assert fork['spec']['initialState'] == spec['initialState']
    assert not (tmp_path / 'sim_fork/world.sqlite3').exists()
    assert parent_bytes == {p.name: p.read_bytes() for p in directory.glob('*.json')}
    with WorldStore(tmp_path / 'sim_fork/world.sqlite3', fork['spec']) as store:
        fork_head = store.head()
    assert fork_head['round'] == 0 and fork_head['sampling'] == {'seed': 19, 'draws': []}
    assert not fork_head['commitments']
    assert all(not a['lastActionResults'] for a in fork_head['actorStates'].values())
    altered = deepcopy(spec)
    altered['policy']['model'] = 'different-model'
    with pytest.raises(WorldError) as error:
        WorldStore(directory / 'world.sqlite3', altered, read_only=True)
    assert error.value.code == 'world_identity_mismatch'


@pytest.mark.parametrize('audience', ['owner', 'public_source', 'analyst'])
def test_assumptions_keep_their_authorized_audience(tmp_path, audience):
    raw, bundle = raw_case()
    text = PUBLIC_FACT if audience == 'public_source' else PRIVATE_GOAL
    visibility = {'kind': 'actors', 'actorIds': ['producer']} if audience == 'owner' else {
        'kind': 'public' if audience == 'public_source' else 'analyst'}
    raw['initialState']['rules']['context_control'] = {
        'value': text, 'visibility': visibility, 'basis': deepcopy(BASIS)}
    prepared, directory = prepare(tmp_path, raw, bundle)
    sent = []
    policy, sdk = http_policy(prepared['spec'], sent)
    try:
        assert run_child(directory, policy=policy) == 0
    finally:
        policy.close()
        sdk.close()
    observations = [json.loads(body['messages'][1]['content']) for body in sent]
    for obs in observations:
        expected = audience == 'public_source' or audience == 'owner' and obs['actorId'] == 'producer'
        assert ('context_control' in obs['world']['rules']) == expected
    assert ('context_control' in load_frozen_result(directory)['world']['rules']) == (audience == 'public_source')


@pytest.mark.parametrize('known_usage', [False, True])
def test_interrupted_round_reuses_successful_slots_and_exact_actor_context(tmp_path, known_usage):
    prepared, directory = prepare(tmp_path)
    class Interrupted(ExamplePolicy):
        def decide(self, obs):
            if obs['actorId'] == 'buyer':
                if known_usage:
                    raise PolicyFailure('policy_invalid_response', 'Scripted invalid output',
                                        usage={'tokens': 0, 'costUsd': '0'})
                raise RuntimeError('scripted actor response unavailable')
            return super().decide(obs)
    with WorldStore(directory / 'world.sqlite3', prepared['spec']) as store:
        fence = store.acquire_writer('interrupted')
        with pytest.raises(WorldError) as error:
            run_round(store, Interrupted('investment'), fence)
        assert error.value.code == 'required_decision_failed'
        assert store.head()['round'] == 0
        persisted = store.observation('1:proposal:producer')
        assert persisted['actor']['objectives'][0]['text'] == PRIVATE_GOAL
        assert store.decision('1:proposal:producer') is not None
        # Known failures consume their allowance; abandoned unknown outcomes
        # permit reconstruction while keeping their exposure in the journal.
        before_budget = store.budget_summary()
        store.release_writer(fence)
    resumed = ExamplePolicy('investment')
    assert run_child(directory, policy=resumed) == (1 if known_usage else 0)
    assert not any(o['round'] == 1 and o['phase'] == 'proposal' and o['actorId'] != 'buyer'
                   for o in resumed.observations)
    with WorldStore(directory / 'world.sqlite3', prepared['spec'], read_only=True) as store:
        assert store.head()['round'] == (0 if known_usage else 3)
        assert store.observation('1:proposal:producer') == persisted
        if known_usage:
            assert store.budget_summary() == before_budget
        else:
            assert len(store.budget_summary()['attempts']) > len(before_budget['attempts'])


def test_changed_source_does_not_reuse_modeling_candidate(tmp_path):
    from app.services.world_simulation.controller import PolicyResponse
    from app.services.world_simulation.modeler import generate_candidate

    raw, bundle = raw_case()
    class Modeler:
        calls = 0
        def reservation(self, messages):
            return {'tokens': 1000, 'costUsd': '0.1'}
        def decide(self, messages):
            self.calls += 1
            return PolicyResponse(deepcopy(raw), {'tokens': 100, 'costUsd': '0.01'})
    inputs = dict(research_report=REPORT, research_generation_id='research_context', research_engine='v3',
        actor_bundle=bundle, ontology={}, simulation_requirement='Trace the declared scenario.',
        policy_spec={'policy': raw['policy'], 'limits': raw['limits']})
    boundary = Modeler()
    first = generate_candidate(tmp_path, transport=boundary, **inputs)
    assert generate_candidate(tmp_path, transport=boundary, **inputs) == first
    assert boundary.calls == 1
    inputs['actor_bundle'] = deepcopy(bundle)
    inputs['actor_bundle']['actors'][0]['goals'] = ['Preserve a different confidential reserve']
    with pytest.raises(WorldError) as error:
        generate_candidate(tmp_path, transport=boundary, **inputs)
    assert error.value.code == 'modeling_binding_mismatch' and boundary.calls == 1


@pytest.mark.parametrize('kind', ['message', 'agreement'])
@pytest.mark.parametrize('view', ['actor', 'public'])
def test_result_projection_respects_message_delivery_time(tmp_path, view, kind):
    raw, bundle = raw_case()
    template = raw['actionCatalog'][-1]
    template['kind'] = kind
    template['parameters'].update(recipientIds=['buyer'], messageDelayDays='2')
    if kind == 'agreement':
        template['parameters'].update(transfers=[], durationDays='0')
    template['visibility'] = {'kind': 'public'} if view == 'public' else {
        'kind': 'actors', 'actorIds': ['producer', 'buyer']}
    prepared, directory = prepare(tmp_path, raw, bundle)
    marker = 'The shipment message is not delivered until the third day'
    class Sender:
        external = False
        def decide(self, obs):
            return {'actorId': obs['actorId'], 'observationId': obs['observationId'], 'intents': [
                {'templateId': 'communicate', 'operation': 'propose' if kind == 'agreement' else 'execute',
                 'parameters': {'text': marker}}
            ] if obs['round'] == 1 and obs['phase'] == 'proposal' and obs['actorId'] == 'producer' else []}
    kwargs = {'view': view, **({'actor_id': 'buyer'} if view == 'actor' else {})}
    with WorldStore(directory / 'world.sqlite3', prepared['spec']) as store:
        fence = store.acquire_writer('delivery-check')
        run_round(store, Sender(), fence)
        assert marker in canonical_json(read_result(directory, view='analyst'))
        assert marker in canonical_json(read_result(directory, view='actor', actor_id='producer'))
        early = read_result(directory, **kwargs)
        assert marker not in canonical_json(early), 'Result disclosed a message before its delivery boundary'
        assert all(e['kind'] != kind + '_accepted' for e in early['events'])
        run_round(store, Sender(), fence)
        later = read_result(directory, **kwargs)
        assert marker in canonical_json(later['world']['interactions'])
        assert any(e['kind'] == kind + '_accepted' for e in later['events'])
        assert marker not in canonical_json(later['trajectory'][1])
        historical = read_result(directory, round_index=1, **kwargs)
        assert marker not in canonical_json(historical)
        store.release_writer(fence)


# Adapted from accepted causal-order regression scenarios at fe2276a2.
# Kept in this worker-owned test path; production consumers remain real.
START = "2030-01-01T00:00:00Z"
GENERATIONS = tuple(f"causal_scenario_{index:02d}" for index in range(8))


def _record(**fields):
    return {
        "basis": {"kind": "scenario_assumption", "refs": ["causal-order-fixture-v1"]},
        "visibility": {"kind": "public"},
        **fields,
    }


def _template(template_id, kind, parameters, *, actors=("a",), inputs=None):
    return _record(templateId=template_id, kind=kind, actorIds=list(actors),
                   parameters=parameters, inputs=inputs or {})


def _spec(generation, *, causal=True, inbox_limit=20, scheduled=False):
    """Small independent world: scarce cash, a permit, and a funded agreement."""
    catalog = [
        _template("wait", "wait", {}, actors=("a", "b", "c", "authority")),
        *[_template(f"pay_{recipient}", "transfer", {
            "fromAccount": "a_cash", "toAccount": f"{recipient}_cash", "amount": "7",
        }) for recipient in ("b", "c")],
        *[_template(name, "policy", {
            "ruleId": "permit", "value": value, "durationDays": "2",
            "authorityIds": ["authority"],
        }, actors=("authority",)) for name, value in (("close", False), ("reopen", True))],
        _template("expand", "investment", {
            "fromAccount": "a_cash", "toAccount": "sink", "cost": "6",
            "targetMetric": "capacity", "delta": "3", "durationDays": "0",
            "requiresRule": "permit",
        }),
        _template("order", "agreement", {
            "recipientIds": ["b"], "durationDays": "2", "offerTtlDays": "5",
            "transfers": [
                {"fromAccount": "a_cash", "toAccount": "b_cash", "amount": "2"},
                {"fromAccount": "b_stock", "toAccount": "a_stock", "amount": "1"},
            ],
        }, inputs={"label": {"type": "string", "required": True}}),
        _template("say", "message", {"recipientIds": ["b"], "offerTtlDays": "5"},
                  inputs={"text": {"type": "string", "required": True}}),
    ]
    actors = [
        {"actorId": aid, "name": aid, "objectives": ["retain resources"],
         "values": ["honor accepted agreements"], "incentives": [], "constraints": [],
         "beliefs": [], "evidenceGrade": "scenario-assumption",
         "capabilities": [t["templateId"] for t in catalog if aid in t["actorIds"]],
         "basis": _record()["basis"]}
        for aid in ("a", "b", "c", "authority")
    ]
    spec = {
        "schemaVersion": "simulation-world-spec/v1", "engine": "world-v1",
        "simulationId": "sim_causal_order", "generationId": generation, "actors": actors,
        "periods": [{"start": add_days(START, day), "end": add_days(START, day + 1)}
                    for day in range(3)],
        "limits": {"maxIntentsPerPhase": 6, "maxInboxItems": inbox_limit, "maxConcurrentCalls": 1},
        "initialState": {
            "accounts": {
                "a_cash": _record(ownerId="a", unit="currency", balance="10"),
                "b_cash": _record(ownerId="b", unit="currency", balance="0"),
                "c_cash": _record(ownerId="c", unit="currency", balance="0"),
                "sink": _record(ownerId="external", unit="currency", balance="0"),
                "a_stock": _record(ownerId="a", unit="goods", balance="0"),
                "b_stock": _record(ownerId="b", unit="goods", balance="2"),
            },
            "metrics": {"capacity": _record(kind="rate", unit="goods_per_day", value="4")},
            "rules": {"permit": _record(value=False)}, "relations": {},
        },
        "actionCatalog": catalog, "flows": [], "scheduledEvents": [],
    }
    if causal:
        spec["resolutionOrderPolicy"] = "causal-v1"
    if scheduled:
        spec["scheduledEvents"] = [_record(
            eventId="z_declared_permit_close", at=add_days(START, 2), kind="rule_set",
            parameters={"ruleId": "permit", "value": False},
        )]
    return validate_spec(spec)


def _intent(template_id, *, priority=0, operation="execute", parameters=None, **fields):
    return {"templateId": template_id, "operation": operation, "priority": priority,
            "parameters": parameters or {}, **fields}


def _decision(spec, snapshot, actor, intents):
    observation = build_observation(spec, snapshot, actor, snapshot["round"] + 1)
    return validate_decision(spec, {
        "actorId": actor, "observationId": observation["observationId"], "intents": intents,
    }, actor, observation, phase="proposal")


def _advance(spec, snapshot, decisions=()):
    return resolve_round(spec, snapshot, list(decisions), snapshot["round"] + 1)


def _resolution_order(result, decision):
    names = {item["intentId"]: item["templateId"] for item in decision["intents"]}
    return [(names[row["intentId"]], row["accepted"]) for row in result["resolutions"]]


@pytest.mark.parametrize("submitted", [("pay_b", "pay_c"), ("pay_c", "pay_b")])
def test_equal_priority_scarce_actions_follow_submission_order_across_generations(submitted):
    identities = []
    for generation in GENERATIONS:
        spec = _spec(generation)
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "a", [_intent(name) for name in submitted])
        before = deepcopy((opening, decision))
        result = _advance(spec, opening, [decision])
        assert _resolution_order(result, decision) == [(submitted[0], True), (submitted[1], False)], generation
        accounts = result["snapshot"]["accounts"]
        assert accounts["a_cash"]["balance"] == "3"
        assert accounts[submitted[0].removeprefix("pay_") + "_cash"]["balance"] == "7"
        assert accounts[submitted[1].removeprefix("pay_") + "_cash"]["balance"] == "0"
        assert (opening, decision) == before
        identities.append(tuple(item["intentId"] for item in decision["intents"]))
    assert len(set(identities)) == len(GENERATIONS)


def test_explicit_priority_overrides_original_position():
    for generation in GENERATIONS:
        spec = _spec(generation)
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "a", [
            _intent("pay_b", priority=5), _intent("pay_c", priority=-1),
        ])
        result = _advance(spec, opening, [decision])
        assert _resolution_order(result, decision) == [("pay_c", True), ("pay_b", False)], generation
        assert result["snapshot"]["accounts"]["c_cash"]["balance"] == "7"


@pytest.mark.parametrize("affordable", [True, False])
def test_atomic_bundles_preserve_tied_member_order_and_rollback(affordable):
    for generation in GENERATIONS:
        spec = _spec(generation)
        if affordable:
            # Two three-unit transfers fit as one group; the later seven-unit action cannot.
            for item in spec["actionCatalog"]:
                if item["templateId"] in {"pay_b", "pay_c"}:
                    item["parameters"]["amount"] = "3"
            spec["actionCatalog"].append(_template("spend_rest", "transfer", {
                "fromAccount": "a_cash", "toAccount": "sink", "amount": "7",
            }))
            next(actor for actor in spec["actors"] if actor["actorId"] == "a")["capabilities"].append("spend_rest")
            last = "spend_rest"
        else:
            last = "pay_b"
        spec = validate_spec(spec)
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "a", [
            _intent("pay_b", bundleId="pair"), _intent("pay_c", bundleId="pair"), _intent(last),
        ])
        result = _advance(spec, opening, [decision])
        expected = [("pay_b", affordable), ("pay_c", affordable), (last, not affordable)]
        assert _resolution_order(result, decision) == expected, generation
        accounts = result["snapshot"]["accounts"]
        assert accounts["a_cash"]["balance"] == ("4" if affordable else "3")
        assert accounts["b_cash"]["balance"] == ("3" if affordable else "7")
        assert accounts["c_cash"]["balance"] == ("3" if affordable else "0")
        assert accounts["sink"]["balance"] == "0"
        if not affordable:
            assert [row["code"] for row in result["resolutions"][:2]] == ["bundle_rejected"] * 2
            assert len(result["events"]) == 1


@pytest.mark.parametrize("submitted,priorities,expected", [
    (("close", "reopen"), (0, 0), ("close", "reopen")),
    (("reopen", "close"), (0, 0), ("reopen", "close")),
    (("close", "reopen"), (1, 0), ("reopen", "close")),
])
def test_simultaneous_delayed_policies_have_causal_semantics(submitted, priorities, expected):
    for generation in GENERATIONS:
        spec = _spec(generation)
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "authority", [
            _intent(name, priority=priority) for name, priority in zip(submitted, priorities)
        ])
        first = _advance(spec, opening, [decision])
        assert all(row["accepted"] for row in first["resolutions"])
        assert first["snapshot"]["rules"]["permit"]["value"] is False
        assert len(first["snapshot"]["commitments"]) == 2
        assert all(item["status"] == "pending" for item in first["snapshot"]["commitments"].values())
        second = _advance(spec, first["snapshot"])
        by_id = second["snapshot"]["commitments"]
        settled = [by_id[event["details"]["commitmentId"]]["templateId"]
                   for event in second["events"] if event["kind"] == "commitment_settled"]
        assert settled == list(expected), generation
        assert second["snapshot"]["rules"]["permit"]["value"] is (expected[-1] == "reopen"), generation
        assert all(item["status"] == "settled" for item in by_id.values())


def test_declared_schedule_precedes_simultaneous_policy_commitments():
    for generation in GENERATIONS:
        spec = _spec(generation, scheduled=True)
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "authority", [_intent("close"), _intent("reopen")])
        first = _advance(spec, opening, [decision])["snapshot"]
        second = _advance(spec, first)
        assert [event["kind"] for event in second["events"]] == [
            "scheduled_rule_set", "commitment_settled", "commitment_settled",
        ], generation
        assert second["snapshot"]["rules"]["permit"]["value"] is True


class _FeedbackPolicy:
    """Local model substitute that branches only on the actual observation."""
    external = False

    def __init__(self):
        self.observations = []

    def decide(self, observation):
        self.observations.append(deepcopy(observation))
        actor, phase, round_index = observation["actorId"], observation["phase"], observation["round"]
        intents = []
        if phase == "response":
            intents = [_intent(item["templateId"], operation="accept",
                               interactionId=item["interactionId"], termsVersion=item["termsVersion"])
                       for item in observation["inbox"]]
        elif actor == "authority" and round_index == 1:
            intents = [_intent("close"), _intent("reopen")]
        elif actor == "a":
            if round_index == 1:
                intents = [_intent("order", operation="propose", parameters={"label": "reserved-order"})]
            elif observation["world"]["rules"]["permit"]["value"]:
                intents = [_intent("expand")]
            else:
                intents = [_intent("wait")]
        return {"actorId": actor, "observationId": observation["observationId"], "intents": intents}


def _store_evidence(store):
    return {"head": store.head(), "history": store.history(), "rounds": store.rounds(),
            "events": store.events(), "resolutions": store.resolutions()}


def _assert_feedback(store, policy):
    observed = [item for item in policy.observations if item["actorId"] == "a" and item["phase"] == "proposal"]
    assert [item["world"]["rules"]["permit"]["value"] for item in observed] == [False, False, True]
    assert [item["world"]["metrics"]["capacity"]["value"] for item in observed] == ["4", "4", "4"]
    assert [item["templateId"] for item in store.decision("2:proposal:a")["intents"]] == ["wait"]
    assert [item["templateId"] for item in store.decision("3:proposal:a")["intents"]] == ["expand"]
    assert store.decision("3:proposal:a")["observationId"] == observed[-1]["observationId"]
    final = store.head()
    assert final["metrics"]["capacity"]["value"] == "7"
    assert final["accounts"]["a_cash"]["balance"] == "2"
    assert final["accounts"]["b_cash"]["balance"] == "2"
    assert final["accounts"]["a_stock"]["balance"] == "1"
    assert final["accounts"]["b_stock"]["balance"] == "1"
    assert final["accounts"]["sink"]["balance"] == "6"
    assert all(item["reserved"] == "0" for item in final["accounts"].values())
    assert all(item["status"] == "settled" for item in final["commitments"].values())
    assert all(item["accepted"] for item in store.resolutions())


@pytest.mark.parametrize("generation", GENERATIONS)
def test_actual_controller_feedback_and_store_restart_match_uninterrupted(tmp_path, generation):
    spec = _spec(generation)
    full_policy = _FeedbackPolicy()
    with WorldStore(tmp_path / "full.sqlite3", spec) as full:
        fence = full.acquire_writer("full")
        for _ in range(3):
            run_round(full, full_policy, fence)
        _assert_feedback(full, full_policy)
        expected = _store_evidence(full)
        full.release_writer(fence)

    path = tmp_path / "resumed.sqlite3"
    resumed_policy = _FeedbackPolicy()
    with WorldStore(path, spec) as first:
        fence = first.acquire_writer("first")
        pending = run_round(first, resumed_policy, fence)
        assert pending["rules"]["permit"]["value"] is False
        assert pending["accounts"]["a_cash"]["reserved"] == "2"
        assert pending["accounts"]["b_stock"]["reserved"] == "1"
        assert len(pending["commitments"]) == 3
        assert all(item["status"] == "pending" for item in pending["commitments"].values())
        first.release_writer(fence)
    with WorldStore(path) as restored:
        assert restored.head() == pending
        assert restored.spec["resolutionOrderPolicy"] == "causal-v1"
        fence = restored.acquire_writer("restored")
        for _ in range(2):
            run_round(restored, resumed_policy, fence)
        _assert_feedback(restored, resumed_policy)
        assert _store_evidence(restored) == expected
        assert resumed_policy.observations == full_policy.observations
        restored.release_writer(fence)


def _communications():
    return [*[_intent("order", operation="propose", parameters={"label": f"offer-{index}"})
              for index in range(3)],
            *[_intent("say", parameters={"text": f"message-{index}"}) for index in range(3)]]


def _labels(items):
    return [item["terms"].get("label", item["terms"].get("text")) for item in items]


@pytest.mark.parametrize("inbox_limit", [2, 20])
def test_inbox_messages_and_own_offers_follow_causal_delivery_across_generations(inbox_limit):
    identities = []
    for generation in GENERATIONS:
        spec = _spec(generation, inbox_limit=inbox_limit)
        spec["interactionQueuePolicy"] = "presented-v1"
        spec = validate_spec(spec)
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "a", _communications())
        staged = stage_interactions(spec, opening, [decision], 1)
        committed = _advance(spec, opening, [decision])
        assert all(row["accepted"] for row in committed["resolutions"])
        # Canonical serialization deliberately destroys insertion-order shortcuts.
        restored = json.loads(canonical_json(committed["snapshot"]))
        for snapshot, round_index in ((staged, 1), (restored, 2)):
            recipient = build_observation(spec, snapshot, "b", round_index, "response")
            sender = build_observation(spec, snapshot, "a", round_index)
            assert _labels(recipient["inbox"]) == [f"offer-{i}" for i in range(3)][:inbox_limit], generation
            assert _labels(recipient["messages"]) == [f"message-{i}" for i in range(3)][-inbox_limit:], generation
            assert _labels(sender["ownOffers"]) == [
                "offer-0", "offer-1", "offer-2", "message-0", "message-1", "message-2",
            ], generation
        identities.append(frozenset(restored["interactions"]))
    assert len(set(identities)) == len(GENERATIONS)


def test_absent_pin_preserves_legacy_action_and_delayed_effect_order():
    for generation in GENERATIONS:
        spec = _spec(generation, causal=False)
        assert "resolutionOrderPolicy" not in spec
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "a", [_intent("pay_b"), _intent("pay_c")])
        legacy_actions = sorted(decision["intents"], key=lambda item: item["intentId"])
        result = _advance(spec, opening, [decision])
        assert _resolution_order(result, decision) == [
            (legacy_actions[0]["templateId"], True), (legacy_actions[1]["templateId"], False),
        ]
        decision = _decision(spec, opening, "authority", [_intent("close"), _intent("reopen")])
        first = _advance(spec, opening, [decision])["snapshot"]
        legacy_commitments = sorted(first["commitments"].values(), key=lambda item: stable_id(
            generation, item["commitmentId"], "commitment_settled"))
        second = _advance(spec, first)
        assert [event["details"]["commitmentId"] for event in second["events"]] == [
            item["commitmentId"] for item in legacy_commitments
        ]
        assert second["snapshot"]["rules"]["permit"]["value"] is (
            legacy_commitments[-1]["templateId"] == "reopen"
        )


def test_absent_pin_preserves_legacy_inbox_messages_and_own_offer_order():
    for generation in GENERATIONS:
        spec = _spec(generation, causal=False, inbox_limit=2)
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "a", _communications())
        committed = _advance(spec, opening, [decision])["snapshot"]
        records = sorted(committed["interactions"].values(), key=lambda item: item["interactionId"])
        recipient = build_observation(spec, committed, "b", 2, "response")
        sender = build_observation(spec, committed, "a", 2)
        assert recipient["inbox"] == [item for item in records if item["status"] == "pending"][:2]
        assert recipient["messages"] == [item for item in records if item.get("kind") == "message"][-2:]
        assert sender["ownOffers"] == records


@pytest.mark.parametrize("bad_policy", [None, False, "future-v2", {}, []])
def test_unknown_explicit_resolution_policy_rejects(bad_policy):
    spec = _spec("invalid-order-policy", causal=False)
    spec["resolutionOrderPolicy"] = bad_policy
    with pytest.raises(WorldError) as error:
        validate_spec(spec)
    assert error.value.code == "unsupported_order_policy"


@pytest.mark.parametrize("field", ["_position", "internal_position"])
def test_model_authored_internal_position_is_rejected_at_decision_boundary(field):
    spec = _spec("model-position-injection")
    opening = initialize_world(spec)
    observation = build_observation(spec, opening, "a", 1)
    raw = {"actorId": "a", "observationId": observation["observationId"],
           "intents": [_intent("pay_b"), _intent("pay_c")]}
    valid = validate_decision(spec, raw, "a", observation, phase="proposal")
    assert _resolution_order(_advance(spec, opening, [valid]), valid) == [
        ("pay_b", True), ("pay_c", False),
    ]
    raw["intents"][1][field] = -100
    with pytest.raises(WorldError) as error:
        validate_decision(spec, raw, "a", observation, phase="proposal")
    assert error.value.code == "invalid_intent"


def test_kernel_derives_positions_from_normalized_list_instead_of_injected_metadata():
    spec = _spec("normalized-position-injection")
    opening = initialize_world(spec)
    decision = _decision(spec, opening, "a", [_intent("pay_b"), _intent("pay_c")])
    expected = _advance(spec, opening, [decision])
    supplied = deepcopy(decision)
    supplied["intents"][0]["_position"] = 100
    supplied["intents"][1]["_position"] = -100
    before = deepcopy(supplied)
    actual = _advance(spec, opening, [supplied])
    assert actual == expected
    assert _resolution_order(actual, supplied) == [("pay_b", True), ("pay_c", False)]
    assert supplied == before


@pytest.mark.parametrize("damage", [
    "missing-map", "non-mapping", "missing-record", "extra-record",
    "malformed-origin", "wrong-actor", "wrong-phase", "out-of-range-position",
])
def test_snapshot_validation_rejects_missing_or_malformed_causal_origins(damage):
    spec = _spec("invalid-causal-snapshot")
    opening = initialize_world(spec)
    decisions = [
        _decision(spec, opening, "a", [_intent("order", operation="propose",
                                              parameters={"label": "validation-offer"})]),
        _decision(spec, opening, "authority", [_intent("close")]),
    ]
    valid = _advance(spec, opening, decisions)["snapshot"]
    validate_snapshot(spec, valid)
    assert valid["interactions"] and valid["commitments"]
    damaged = deepcopy(valid)
    record_id = next(iter(valid["interactions"]))
    if damage == "missing-map":
        damaged.pop("causalOrder")
    elif damage == "non-mapping":
        damaged["causalOrder"] = []
    elif damage == "missing-record":
        damaged["causalOrder"].pop(record_id)
    elif damage == "extra-record":
        damaged["causalOrder"]["uncreated-record"] = deepcopy(valid["causalOrder"][record_id])
    elif damage == "malformed-origin":
        damaged["causalOrder"][record_id] = []
    elif damage == "wrong-actor":
        damaged["causalOrder"][record_id][2] = "b"
    elif damage == "wrong-phase":
        damaged["causalOrder"][record_id][1] = "response"
    else:
        damaged["causalOrder"][record_id][4] = spec["limits"]["maxIntentsPerPhase"]
    with pytest.raises(WorldError) as error:
        validate_snapshot(spec, damaged)
    assert error.value.code == "invalid_causal_order"
    validate_snapshot(spec, valid)


def test_causal_map_and_internal_positions_do_not_leak_into_actor_or_public_views(tmp_path):
    from app.services.world_simulation.artifacts import seal_inputs
    from app.services.world_simulation.results import read_result

    spec = _spec("causal-projection")
    directory = tmp_path / "prepared"
    seal_inputs(directory, spec)
    policy = _FeedbackPolicy()
    with WorldStore(directory / "world.sqlite3", spec) as store:
        fence = store.acquire_writer("projection")
        head = run_round(store, policy, fence)
        assert head["causalOrder"] and head["commitments"] and head["interactions"]
        store.release_writer(fence)
    for actor in spec["actors"]:
        observation = build_observation(spec, head, actor["actorId"], 2)
        # Change private priorities uniformly so ordering stays the same. Even
        # the observation hash must not expose this unprojected root metadata.
        altered = deepcopy(head)
        for origin in altered["causalOrder"].values():
            origin[3] += 987654
        assert build_observation(spec, altered, actor["actorId"], 2) == observation
        policy.observations.append(observation)
    views = [read_result(directory, view="public")]
    views.extend(read_result(directory, view="actor", actor_id=actor["actorId"])
                 for actor in spec["actors"])
    for output in [*policy.observations, *views]:
        encoded = canonical_json(output)
        assert '"causalOrder"' not in encoded
        assert '"_position"' not in encoded
        assert '"internal_position"' not in encoded
    for view in views:
        assert view["world"]["commitments"] and view["world"]["interactions"]
        # Actor result decisions legitimately retain the actor's own priority;
        # visible world records and trajectories must not gain that field.
        assert '"priority"' not in canonical_json(view["world"])
        assert '"priority"' not in canonical_json(view["trajectory"])


class _PresentedPolicy:
    external = False

    def __init__(self):
        self.responses = []

    def decide(self, observation):
        intents = []
        if observation["phase"] == "response":
            self.responses.append(deepcopy(observation))
        elif observation["actorId"] == "a" and observation["round"] == 1:
            intents = _communications()[:3]
        return {"actorId": observation["actorId"], "observationId": observation["observationId"],
                "intents": intents}


@pytest.mark.parametrize("generation", GENERATIONS[:3])
def test_presented_queue_accounts_for_the_same_causal_offer_shown_to_the_controller(tmp_path, generation):
    spec = _spec(generation, inbox_limit=1)
    spec["interactionQueuePolicy"] = "presented-v1"
    spec = validate_spec(spec)
    policy = _PresentedPolicy()
    with WorldStore(tmp_path / "world.sqlite3", spec) as store:
        fence = store.acquire_writer("presented-order")
        for round_index in range(1, 4):
            head = run_round(store, policy, fence)
            observation = policy.responses[-1]
            assert observation["actorId"] == "b" and observation["round"] == round_index
            assert _labels(observation["inbox"]) == [f"offer-{round_index - 1}"]
            presented = observation["inbox"][0]["interactionId"]
            assert head["interactionQueueState"]["b"][presented] == round_index
            response = store.decision(f"{round_index}:response:b")
            assert response["intents"] == []
            assert response["observationId"] == observation["observationId"]
        assert len(policy.responses) == 3
        by_id = head["interactions"]
        assert {by_id[key]["terms"]["label"]: value
                for key, value in head["interactionQueueState"]["b"].items()} == {
            "offer-0": 1, "offer-1": 2, "offer-2": 3,
        }
        assert all(item["status"] == "pending" and item["lastResponseRound"] == 0
                   for item in by_id.values())
        store.release_writer(fence)


@pytest.mark.parametrize("limit,wait_accepted", [(3, False), (4, True)])
def test_event_budget_probe_preserves_staged_offer_origins_before_physical_groups(limit, wait_accepted):
    """Public counterpart of test_world_event_limit's staged-budget scenario.

    The empty flow overestimates boundary load. An offer expiring this round
    forces the exact probe to carry its reserved staged origin while evaluating
    preceding physical groups. No private admission helper is called or mocked.
    """
    for generation in GENERATIONS[:3]:
        spec = _spec(generation)
        spec["limits"]["maxEventsPerRound"] = limit
        next(item for item in spec["actionCatalog"] if item["templateId"] == "order")["parameters"].update(
            offerTtlDays="0.5")
        spec["flows"] = [_record(flowId="idle", sourceAccount="c_cash", targetAccount="sink", ratePerDay="1")]
        spec = validate_spec(spec)
        opening = initialize_world(spec)
        decision = _decision(spec, opening, "a", [
            _intent("pay_b", priority=0), _intent("wait", priority=1),
            _intent("order", priority=2, operation="propose", parameters={"label": "reserved-before-physics"}),
        ])
        before = deepcopy((opening, decision))
        staged = stage_interactions(spec, opening, [decision], 1)
        inbox = build_observation(spec, staged, "b", 1, "response")["inbox"]
        assert _labels(inbox) == ["reserved-before-physics"]
        offered_id = inbox[0]["interactionId"]
        result = _advance(spec, opening, [decision])
        assert _resolution_order(result, decision) == [
            ("pay_b", True), ("wait", wait_accepted), ("order", True),
        ], generation
        if not wait_accepted:
            assert result["resolutions"][1]["code"] == "event_limit"
        assert result["snapshot"]["accounts"]["a_cash"]["balance"] == "3"
        assert result["snapshot"]["accounts"]["b_cash"]["balance"] == "7"
        assert result["snapshot"]["interactions"][offered_id]["status"] == "expired"
        expired = [event["details"]["interactionId"] for event in result["events"]
                   if event["kind"] == "offer_expired"]
        assert expired == [offered_id]
        flow_events = [event for event in result["events"] if event["kind"] in {"flow_transfer", "flow_summary"}]
        assert flow_events and all(event["details"]["amount"] == "0" for event in flow_events)
        assert len(result["events"]) - len(flow_events) == limit
        assert _advance(spec, opening, [decision]) == result
        assert (opening, decision) == before


@pytest.mark.parametrize("causal", [False, True])
def test_actual_service_fork_inherits_source_order_policy_without_migrating_legacy(tmp_path, causal):
    from app.services.world_simulation.artifacts import atomic_json, file_digest, load_inputs, seal_inputs
    from app.services.world_simulation.service import WorldSimulationService

    spec = _spec("fork-order-source", causal=causal)
    source_id = spec["simulationId"]
    directory = tmp_path / source_id
    manifest = seal_inputs(directory, spec)
    atomic_json(directory / "state.json", {
        "simulation_engine": "world-v1", "world_generation_id": spec["generationId"],
        "world_input_manifest_sha256": file_digest(directory / "world_input_manifest.json"),
        "world_spec_sha256": manifest["specSha256"],
    })
    before = {path.name: path.read_bytes() for path in directory.glob("*.json")}
    child_id = source_id + "_child"
    child = WorldSimulationService.fork(source_id, child_id, root=tmp_path)
    loaded, _ = load_inputs(tmp_path / child_id)
    assert loaded == child["spec"]
    assert loaded["generationId"] != spec["generationId"]
    assert loaded["simulationId"] == child_id
    if causal:
        assert loaded["resolutionOrderPolicy"] == "causal-v1"
    else:
        assert "resolutionOrderPolicy" not in loaded
    assert {path.name: path.read_bytes() for path in directory.glob("*.json")} == before
    assert not (directory / "world.sqlite3").exists()
    assert not (tmp_path / child_id / "world.sqlite3").exists()


@pytest.mark.parametrize('supplied', ['absent', 'causal-v1', 'legacy', None])
def test_fresh_causal_order_policy_is_compiler_owned(tmp_path, supplied):
    raw, bundle = raw_case()
    if supplied == 'absent':
        prepared, _ = prepare(tmp_path, raw, bundle)
        assert prepared['spec']['resolutionOrderPolicy'] == 'causal-v1'
    else:
        raw['resolutionOrderPolicy'] = supplied
        with pytest.raises(WorldError) as error:
            prepare(tmp_path, raw, bundle)
        assert error.value.code == 'invalid_spec'
