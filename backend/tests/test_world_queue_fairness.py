"""RW17 presentation fairness through the real controller, Store and projections.

These are the approved proposal scenarios, promoted without the temporary
36-case baseline-file dependency. The original exact comparison and its hashes
remain in docs/handoff/reflexive-world-simulation/queue-fairness-investigation.md.
Run this module only through the coordinator's guarded offline runner.
"""
import json
import pytest
from app.services.world_simulation.artifacts import atomic_json, file_digest, load_inputs, seal_inputs
from app.services.world_simulation.contracts import WorldError, clone, digest, stable_id, validate_spec
from app.services.world_simulation.controller import run_round
from app.services.world_simulation.examples import example_spec
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.results import read_result
from app.services.world_simulation.service import WorldSimulationService as Service
from app.services.world_simulation.store import WorldStore

pytestmark = pytest.mark.guarded_runner
PIN = 'presented-v1'
CURSOR = 'interactionQueueState'

class QueuePolicy:
    external = False
    def __init__(self, *, multi=False, fail_recipient=None):
        self.views = []
        self.multi = multi
        self.fail_recipient = fail_recipient
    def decide(self, obs):
        self.views.append(clone(obs))
        if obs['phase']=='response' and obs['actorId']==self.fail_recipient:
            raise ValueError('offline required-slot failure')
        intents=[]
        if obs['actorId']=='buyer' and obs['phase']=='proposal' and obs['round']==1:
            if self.multi:
                slots = sorted(range(2), key=lambda i:stable_id('queue-multi', stable_id('queue-multi',1,'proposal','buyer',i),'offer'))
                templates={slots[0]:'exclusive', slots[1]:'shared'}
                intents=[{'templateId':templates[i], 'operation':'propose'} for i in range(2)]
            else:
                intents=[{'templateId':'purchase', 'operation':'propose', 'parameters':{'quantity':str(i),'price':str(i)}} for i in (1,2)]
        if self.multi and obs['actorId']=='producer' and obs['phase']=='response':
            offer=obs['inbox'][0]
            intents=[{'templateId':offer['templateId'],'operation':'defer','interactionId':offer['interactionId'],'termsVersion':offer['termsVersion']}]
        return {'actorId':obs['actorId'],'observationId':obs['observationId'],'intents':intents}

def queue_spec(*, pin=PIN, multi=False, cap=1, periods=4):
    spec=example_spec(periods=periods, generation_id='queue-multi' if multi else 'queue-simple')
    spec['limits']['maxInboxItems']=cap
    if pin is not None:
        spec['interactionQueuePolicy']=pin
    if multi:
        purchase=next(t for t in spec['actionCatalog'] if t['templateId']=='purchase')
        for tid, recipients in [('exclusive',['financier']),('shared',['producer','financier'])]:
            t=clone(purchase)
            t.update(templateId=tid, inputs={})
            t['parameters']={'recipientIds':recipients, 'transfers':[], 'durationDays':'0'}
            spec['actionCatalog'].append(t)
            next(a for a in spec['actors'] if a['actorId']=='buyer')['capabilities'].append(tid)
    return spec

def shown(policy, actor='producer'):
    return [o['inbox'][0]['interactionId'] for o in sorted(policy.views,key=lambda x:x['round'])
            if o['actorId']==actor and o['phase']=='response']

def run(path, spec, policy, rounds=2):
    with WorldStore(path,spec) as store:
        fence=store.acquire_writer('queue-test')
        for _ in range(rounds):
            run_round(store,policy,fence)
        return store.head(),store.rounds()

def test_waiting_required_recipient_rotates_and_cursor_is_not_an_intent(tmp_path):
    spec=queue_spec()
    policy=QueuePolicy()
    head,rounds=run(tmp_path/'world.sqlite',spec,policy,rounds=4)
    ids=shown(policy)
    assert ids[0]!=ids[1] and ids==[ids[0],ids[1],ids[0],ids[1]]
    assert all(d['intents']==[] for row in rounds for d in row['decisions'] if d['actorId']=='producer' and d['phase']=='response')
    assert set(head[CURSOR])=={'producer'}
    assert head[CURSOR]['producer']=={ids[0]:3,ids[1]:4}
    assert all(row['status']=='pending' for row in head['interactions'].values())

@pytest.mark.parametrize('pin',[None,PIN])
def test_multi_recipient_cursor_is_independent_of_other_recipients_defer(tmp_path,pin):
    spec=queue_spec(pin=pin,multi=True)
    policy=QueuePolicy(multi=True)
    head,_=run(tmp_path/'world.sqlite',spec,policy,rounds=3)
    ids=shown(policy,'financier')
    if pin is None:
        assert ids[0]==ids[1]==ids[2]
        assert CURSOR not in head
    else:
        assert ids[0]!=ids[1] and ids[0]==ids[2]
        assert set(head[CURSOR])=={'financier'}  # Producer never has overflow.
    shared=next(v for v in head['interactions'].values() if v['templateId']=='shared')
    assert shared['lastResponseRound']==3  # Legacy response metadata is not the new scheduler.

@pytest.mark.parametrize('pin',[None,PIN])
def test_no_overflow_adds_no_cursor_and_all_prompt_bytes_match(tmp_path,pin):
    base=queue_spec(pin=None,cap=20)
    other=clone(base)
    if pin is not None:
        other['interactionQueuePolicy']=pin
    first,second=QueuePolicy(),QueuePolicy()
    left,_=run(tmp_path/'old.sqlite',base,first)
    right,_=run(tmp_path/'new.sqlite',other,second)
    order=lambda o:(o['round'],o['phase'],o['actorId'])
    assert sorted(first.views,key=order)==sorted(second.views,key=order)
    assert CURSOR not in left and CURSOR not in right


def test_old_unpinned_spec_validation_and_wait_replay_are_exact(tmp_path):
    spec=queue_spec(pin=None)
    encoded=digest(spec)
    assert validate_spec(spec)==spec and digest(validate_spec(spec))==encoded
    left,rows=run(tmp_path/'left.sqlite',spec,QueuePolicy(),rounds=3)
    right,other=run(tmp_path/'right.sqlite',spec,QueuePolicy(),rounds=3)
    assert left==right and rows==other and CURSOR not in left
    assert 'interactionQueuePolicy' not in spec


def test_presented_cursor_survives_reopen_and_matches_uninterrupted_replay(tmp_path):
    spec=queue_spec()
    expected,_=run(tmp_path/'full.sqlite',spec,QueuePolicy(),rounds=3)
    policy=QueuePolicy()
    path=tmp_path/'resume.sqlite'
    with WorldStore(path,spec) as store:
        fence=store.acquire_writer('first')
        run_round(store,policy,fence)
        store.release_writer(fence)
    with WorldStore(path,spec) as store:
        fence=store.acquire_writer('next')
        run_round(store,policy,fence)
        run_round(store,policy,fence)
        assert store.head()==expected
    assert shown(policy)[0]!=shown(policy)[1]


def test_failed_required_slot_cannot_commit_presentation_cursor(tmp_path):
    spec=queue_spec()
    with WorldStore(tmp_path/'world.sqlite',spec) as store:
        fence=store.acquire_writer('failure')
        before=store.head()
        with pytest.raises(WorldError):
            run_round(store,QueuePolicy(fail_recipient='producer'),fence)
        assert store.head()==before and CURSOR not in store.head()


def test_hidden_ineligible_delayed_and_expired_offers_do_not_create_cursor(tmp_path):
    spec=queue_spec()
    purchase=next(t for t in spec['actionCatalog'] if t['templateId']=='purchase')
    purchase['parameters'].update(messageDelayDays='2',offerTtlDays='1')
    policy=QueuePolicy()
    head,_=run(tmp_path/'world.sqlite',spec,policy)
    assert not shown(policy) and CURSOR not in head


def test_cursors_are_absent_from_all_actor_prompts_and_real_api_views(tmp_path):
    spec=queue_spec()
    directory=tmp_path/'prepared'
    seal_inputs(directory,spec)
    policy=QueuePolicy()
    head,_=run(directory/'world.sqlite3',spec,policy)
    assert CURSOR in head
    for obs in policy.views:
        assert CURSOR not in json.dumps(obs,sort_keys=True)
    changed=clone(head)
    changed[CURSOR]={'producer':{oid:999 for oid in head['interactions']},'financier':{'HIDDEN_CURSOR_SENTINEL':777}}
    for actor in ('buyer','producer','financier','authority'):
        # Same selected offer set/order: unrelated recipients cannot affect this actor.
        if actor!='producer':
            assert build_observation(spec,head,actor,3)==build_observation(spec,changed,actor,3)
        obs=build_observation(spec,changed,actor,3)
        assert CURSOR not in json.dumps(obs) and 'HIDDEN_CURSOR_SENTINEL' not in json.dumps(obs)
    for view,actor in [('public',None),('actor','producer'),('actor','financier')]:
        rendered=read_result(directory,view=view,actor_id=actor)
        assert CURSOR not in json.dumps(rendered,sort_keys=True)

@pytest.mark.parametrize('bad',[None,False,'future-v2',{},[]])
def test_unknown_explicit_queue_policy_rejects_without_default_migration(bad):
    spec=queue_spec(pin=None)
    spec['interactionQueuePolicy']=bad
    with pytest.raises(WorldError) as error:
        validate_spec(spec)
    assert error.value.code=='unsupported_queue_policy'


def test_new_preparation_pins_policy_and_existing_inputs_and_forks_retain_their_version(tmp_path):
    for pin,sid in [(None,'old'),(PIN,'new')]:
        spec=queue_spec(pin=pin)
        spec['simulationId']=sid
        directory=tmp_path/sid
        manifest=seal_inputs(directory,spec)
        atomic_json(directory/'state.json',{'simulation_engine':'world-v1','world_input_manifest_sha256':file_digest(directory/'world_input_manifest.json'),
            'world_generation_id':spec['generationId'],'world_spec_sha256':manifest['specSha256']})
        before={p.name:p.read_bytes() for p in directory.glob('*.json')}
        loaded,_=load_inputs(directory)
        assert loaded.get('interactionQueuePolicy')==pin
        child=Service.fork(sid,sid+'_child',root=tmp_path)
        assert child['spec'].get('interactionQueuePolicy')==pin
        assert {p.name:p.read_bytes() for p in directory.glob('*.json')}==before
    raw=example_spec()
    raw.pop('simulationId');raw.pop('generationId')
    prepared=Service.prepare_model('fresh',raw_spec=raw,research_report='Synthetic scenario assumptions.',
        research_generation_id='research_fixture',research_engine='v3',root=tmp_path)
    assert prepared['spec']['interactionQueuePolicy']==PIN
    assert 'interactionQueuePolicy' not in raw
