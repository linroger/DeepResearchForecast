"""Spending admission/lifecycle through the real target pipeline and HTTP routes."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.services import run_spending as runtime_spending
from app.services.official_data import bridge_module
from tests import test_run_spending_store as store_cases
from tests import test_target_pipeline as pipeline_cases

sp = bridge_module('run_spending')
isolated_latch = store_cases.isolated_latch
runtime = pipeline_cases.runtime
case = pipeline_cases.case
execution = pipeline_cases.execution


def request(case=None):
    return {'prompt': case['question'] if case else 'Synthetic target?', 'mode': 'full', 'depth': 'quick',
            'language': 'English', 'model': 'glm', 'forecast_authority': 'target-first-v1',
            'target_simulation': {'paths': 1, 'periods': 2, 'seed': 0}}


@contextmanager
def prepared(tmp_path, monkeypatch, runtime, req, cap='1.00'):
    m, path, registry, _ = store_cases.synthetic_manifest(tmp_path, cap=cap)
    m['request_sha256'] = sp.hash_payload(req)
    path.write_text(json.dumps(m))
    b = sp.create_authorization(path, registry_dir=registry)
    root = Path(b['root'])
    from app.models.project import ProjectManager
    from app.services.report_agent import ReportManager
    for key, value in {'UPLOAD_FOLDER':root/'uploads','PIPELINE_DATA_DIR':root/'uploads/pipelines',
                       'OASIS_SIMULATION_DATA_DIR':root/'uploads/simulations','DEERFLOW_DIR':root/'deer-flow'}.items():
        monkeypatch.setattr(runtime.config,key,str(value))
    monkeypatch.setattr(ProjectManager,'PROJECTS_DIR',str(root/'uploads/projects'))
    monkeypatch.setattr(ReportManager,'REPORTS_DIR',str(root/'uploads/reports'))
    for key,value in sp.export_environment(b).items():monkeypatch.setenv(key,value)
    with sp.run_lock(b):
        yield b,m


def test_direct_start_binds_before_launch_and_cannot_start_twice(runtime, tmp_path, monkeypatch):
    req=request()
    with prepared(tmp_path,monkeypatch,runtime,req) as (b,m):
        state=runtime.po.PipelineOrchestrator.start(**req)
        bound=state.options[runtime_spending.BINDING_KEY]
        assert bound['pipeline_id']==state.pipeline_id
        assert state.options[runtime_spending.REQUEST_KEY]==req
        assert sp.summary(bound)['reserved_max_microusd']==0
        launched=len(runtime.launched)
        with pytest.raises(sp.SpendingStop):runtime.po.PipelineOrchestrator.start(**req)
        assert len(runtime.launched)==launched
        assert sp.summary(bound)['pipeline_id']==state.pipeline_id


@pytest.mark.parametrize('surface',['spa','sdk'])
def test_both_http_routes_use_common_immutable_admission(runtime,tmp_path,monkeypatch,surface):
    from app.api import research,sdk
    monkeypatch.setattr(research,'preflight_pipeline',lambda **kw:[])
    monkeypatch.setattr(sdk,'preflight_pipeline',lambda **kw:[])
    app=Flask(__name__)
    app.register_blueprint(research.research_bp,url_prefix='/api/research')
    app.register_blueprint(sdk.sdk_bp,url_prefix='/api/v1')
    route='/api/research/run' if surface=='spa' else '/api/v1/run'
    req=request()
    with prepared(tmp_path,monkeypatch,runtime,req):
        response=app.test_client().post(route,json=req)
        assert response.status_code==200,response.json
        saved=runtime.po.PipelineManager.load(response.json['data']['pipeline_id'])
        assert saved['options'][runtime_spending.REQUEST_KEY]==req
        assert saved['options'][runtime_spending.BINDING_KEY]['pipeline_id']==saved['pipeline_id']


@pytest.mark.parametrize('mutation',['question','paths','extra_cap','wrong_mode'])
def test_mismatched_or_extra_http_request_never_launches(runtime,tmp_path,monkeypatch,mutation):
    from app.api import research
    monkeypatch.setattr(research,'preflight_pipeline',lambda **kw:[])
    app=Flask(__name__);app.register_blueprint(research.research_bp,url_prefix='/api/research')
    req=request();changed=deepcopy(req)
    if mutation=='question':changed['prompt']='Other question'
    elif mutation=='paths':changed['target_simulation']['paths']=2
    elif mutation=='extra_cap':changed['budget_usd']=999
    else:changed['mode']='research_only'
    with prepared(tmp_path,monkeypatch,runtime,req) as (b,m):
        response=app.test_client().post('/api/research/run',json=changed)
        assert response.status_code==409,response.json
        assert runtime.launched==[]
        assert sp.summary(b)['pipeline_id']==''
        assert sp.summary(b)['reserved_max_microusd']==0


def test_full_actual_target_pipeline_closes_authority_without_refunds(execution,tmp_path,monkeypatch):
    req=request(execution.case)
    with prepared(tmp_path,monkeypatch,execution,req) as (b,m):
        state=execution.po.PipelineOrchestrator.start(**req)
        bound=state.options[runtime_spending.BINDING_KEY]
        with sp.operation('synthetic-research','first'):
            sp.dispatch('model-main',store_cases.envelope(),lambda:None)
        execution.po.PipelineOrchestrator._run(state)
        assert state.status=='completed',state.error
        assert execution.po.ReportManager.publication_status(state.report_id)['publishable']
        assert sp.summary(bound)['state']=='closed'
        assert sp.summary(bound)['reserved_max_microusd']==600000
        assert state.options['spending_summary_v1']['remaining_microusd']==400000
        assert execution.po.PipelineOrchestrator.delete_pipeline(state.pipeline_id,force=True)['status']=='spending_authority_retained'
        with pytest.raises(sp.SpendingStop):execution.po.PipelineOrchestrator.fork(state.pipeline_id,{'label':'new allowance'})


def test_spending_stop_in_estimator_is_not_a_degraded_success(execution,tmp_path,monkeypatch):
    req=request(execution.case)
    class Denied:
        def chat_json(self,**kwargs):
            sp.dispatch('model-main',store_cases.envelope(),lambda:None)
            sp.dispatch('model-main',store_cases.envelope(),lambda:pytest.fail('denied send'))
    monkeypatch.setattr(pipeline_cases.tp,'_method_gateway',Denied)
    with prepared(tmp_path,monkeypatch,execution,req) as (b,m):
        state=execution.po.PipelineOrchestrator.start(**req)
        execution.po.PipelineOrchestrator._run(state)
        assert state.status=='failed'
        assert state.options['spending_stop_v1']['code']=='budget_exhausted'
        assert state.report_id is None
        assert sp.summary(state.options[runtime_spending.BINDING_KEY])['reserved_max_microusd']==600000


def test_cancel_stops_ledger_before_signalling(runtime,tmp_path,monkeypatch):
    req=request()
    with prepared(tmp_path,monkeypatch,runtime,req):
        state=runtime.po.PipelineOrchestrator.start(**req)
        b=state.options[runtime_spending.BINDING_KEY]
        class Event:
            def set(self):assert sp.summary(b)['state']=='halted_cancelled'
        runtime.po.PipelineOrchestrator._threads[state.pipeline_id]=SimpleNamespace(is_alive=lambda:True)
        runtime.po.PipelineOrchestrator._cancel_events[state.pipeline_id]=Event()
        assert runtime.po.PipelineOrchestrator.cancel(state.pipeline_id)['status']=='cancelling'
        with pytest.raises(sp.SpendingStop):sp.check_active(b)


def test_resume_needs_explicit_proof_and_retains_prior_maximum(execution,tmp_path,monkeypatch):
    runtime = execution
    req=request(execution.case)
    with prepared(tmp_path,monkeypatch,runtime,req) as (b,m):
        state=runtime.po.PipelineOrchestrator.start(**req);bound=state.options[runtime_spending.BINDING_KEY]
        with sp.operation('research','old'):
            sp.dispatch('model-main',store_cases.envelope(),lambda:None)
        from app.services import target_simulation
        original_paths = target_simulation.run_paths
        def failed_paths(*args, **kwargs):
            raise ValueError('synthetic recoverable compute failure')
        monkeypatch.setattr(target_simulation, 'run_paths', failed_paths)
        runtime.po.PipelineOrchestrator._run(state)
        assert state.status == 'failed' and state.stages['research'].status == 'completed'
        assert sp.summary(bound)['state'] == 'paused_recoverable'
        monkeypatch.setattr(target_simulation, 'run_paths', original_paths)
        proof=store_cases.proof(bound,m)
        monkeypatch.setenv('DRF_RUN_SPENDING_RESUME_PROOF',json.dumps(proof))
        resumed=runtime.po.PipelineOrchestrator.resume(state.pipeline_id)
        assert resumed.options[runtime_spending.BINDING_KEY]['generation']==bound['generation']+1
        assert sp.summary(resumed.options[runtime_spending.BINDING_KEY])['remaining_microusd']==400000
        with sp.operation('actor','new'):
            with pytest.raises(sp.SpendingStop,match='budget_exhausted'):
                sp.dispatch('model-main',store_cases.envelope(),lambda:pytest.fail('renewed allowance'))


@pytest.mark.parametrize('mutation',['prompt','paths','periods','seed'])
def test_saved_request_and_mutable_copy_cannot_replace_manifest_authority(runtime,tmp_path,monkeypatch,mutation):
    import httpx
    import openai
    from app.utils import llm_client as lc
    req=request()
    with prepared(tmp_path,monkeypatch,runtime,req,cap='5.00') as (b,m):
        for key,value in {'LLM_PROVIDER':'glm','LLM_MODEL_NAME':'synthetic-model',
                'LLM_API_KEY':'synthetic-key','LLM_BASE_URL':'https://synthetic.invalid/v1',
                'LLM_CACHE_ENABLED':False,'LLM_TELEMETRY_ENABLED':False,'LLM_TIERED_ROUTING':False,
                'LLM_RUN_BUDGET_USD':0,'LLM_RUN_BUDGET_TOKENS':0,'LLM_DISABLE_THINKING':True}.items():
            monkeypatch.setattr(runtime.config,key,value)
        monkeypatch.setattr(openai._base_client,'platform_headers',lambda *a,**k:{})
        entered=[]
        def send(request):
            entered.append(json.loads(request.content))
            return httpx.Response(200,json={'id':'synthetic-response','object':'chat.completion','created':0,
                'model':'synthetic-model','usage':{'prompt_tokens':2,'completion_tokens':2,'total_tokens':4},
                'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'ok'}}]})
        http=httpx.Client(transport=httpx.MockTransport(send),trust_env=False,follow_redirects=False)
        monkeypatch.setattr(lc.LLMClient,'_build_http_client',staticmethod(lambda:http))
        state=runtime.po.PipelineOrchestrator.start(**req);bound=state.options[runtime_spending.BINDING_KEY]
        try:
            with runtime_spending.pipeline_scope(state):
                client=lc.LLMClient()
                assert client.chat([{'role':'user','content':state.prompt}],max_tokens=20)=='ok'
            assert len(entered)==1
            if mutation=='prompt':
                state.prompt='Changed task'
                state.options[runtime_spending.REQUEST_KEY]['prompt']=state.prompt
            else:
                value=state.options['target_simulation'][mutation]+1
                state.options['target_simulation'][mutation]=value
                state.options[runtime_spending.REQUEST_KEY]['target_simulation'][mutation]=value
            with pytest.raises(sp.SpendingStop,match='binding_conflict'):
                with runtime_spending.pipeline_scope(state):
                    client.chat([{'role':'user','content':state.prompt}],max_tokens=20)
            assert len(entered)==1
            assert sp.summary(bound)['reserved_max_microusd']==120000
        finally:
            http.close()


def test_changed_saved_request_is_refused_before_resume_generation_advance(runtime,tmp_path,monkeypatch):
    req=request()
    with prepared(tmp_path,monkeypatch,runtime,req) as (b,m):
        state=runtime.po.PipelineOrchestrator.start(**req);bound=state.options[runtime_spending.BINDING_KEY]
        sp.mark_recoverable(bound)
        state.status='failed';state.prompt='Changed task';state.options[runtime_spending.REQUEST_KEY]['prompt']=state.prompt
        runtime.po.PipelineManager.save(state)
        monkeypatch.setenv('DRF_RUN_SPENDING_RESUME_PROOF',json.dumps(store_cases.proof(bound,m)))
        with pytest.raises(sp.SpendingStop,match='binding_conflict'):
            runtime.po.PipelineOrchestrator.resume(state.pipeline_id)
        assert sp.summary(bound)['generation']==1
        assert len(runtime.launched)==1


def test_unsealed_research_resume_is_explicitly_unsupported(runtime,tmp_path,monkeypatch):
    req=request()
    with prepared(tmp_path,monkeypatch,runtime,req) as (b,m):
        state=runtime.po.PipelineOrchestrator.start(**req);bound=state.options[runtime_spending.BINDING_KEY]
        sp.mark_recoverable(bound);state.status='failed';runtime.po.PipelineManager.save(state)
        monkeypatch.setenv('DRF_RUN_SPENDING_RESUME_PROOF',json.dumps(store_cases.proof(bound,m)))
        with pytest.raises(sp.SpendingStop,match='resume_denied'):
            runtime.po.PipelineOrchestrator.resume(state.pipeline_id)
        assert sp.summary(bound)['generation']==1 and len(runtime.launched)==1


def test_direct_start_persists_only_the_normalized_approved_request(runtime,tmp_path,monkeypatch):
    req=request()
    with prepared(tmp_path,monkeypatch,runtime,req):
        changed=deepcopy(req);changed['prompt']='  '+req['prompt']+'  ';changed['model']=' GLM '
        state=runtime.po.PipelineOrchestrator.start(**changed)
        assert state.prompt==req['prompt']
        assert state.options['research_model']==req['model']
        assert state.options[runtime_spending.REQUEST_KEY]==req
