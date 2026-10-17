"""World report consumers use frozen bytes and evidence-only probability prompts."""
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services.report_agent import ReportAgent, ReportManager
from app.services.world_simulation.artifacts import atomic_json, file_digest, seal_inputs
from app.services.world_simulation.contracts import WorldError
from app.services.world_simulation.controller import run_to_horizon
from app.services.world_simulation.examples import ExamplePolicy, example_spec
from app.services.world_simulation.results import export_result
from app.services.world_simulation.store import WorldStore
from tests.conftest import FakeLLMClient

pytestmark = pytest.mark.guarded_runner


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / 'simulations'
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(root))
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(tmp_path / 'reports'))
    def create(domain='investment', effect='diagnostic_only', periods=4, capacity='4', identity='sim_example', category=False):
        spec = example_spec(domain, periods=periods, simulation_id=identity)
        spec['forecastEffect'] = effect
        if domain == 'investment':
            spec['initialState']['metrics']['capacity']['value'] = capacity
        if category:
            spec['initialState']['metrics']['access'] = {
                'kind': 'category', 'value': 'open', 'unit': 'status',
                'visibility': {'kind': 'public'}, 'basis': {'kind': 'scenario_assumption', 'refs': ['fixture']}}
        directory = root / spec['simulationId']
        seal_inputs(directory, spec)
        with WorldStore(directory / 'world.sqlite3', spec) as store:
            run_to_horizon(store, ExamplePolicy(domain), store.acquire_writer('test'))
        export_result(directory)
        atomic_json(directory / 'state.json', {
            'simulation_id': spec['simulationId'], 'simulation_engine': 'world-v1',
            'world_generation_id': spec['generationId'],
            'world_spec_sha256': file_digest(directory / 'world_spec.json'),
            'world_input_manifest_sha256': file_digest(directory / 'world_input_manifest.json'),
        })
        return directory
    return create


def agent(directory, **kwargs):
    return ReportAgent('graph_test', directory.name, 'What happens by 2027?',
                       llm_client=kwargs.pop('llm_client', FakeLLMClient()),
                       zep_tools=object(), **kwargs)


def test_constructor_rejects_missing_required_world_result(world):
    directory = world()
    (directory / 'world_result.json').unlink()
    with pytest.raises(WorldError):
        agent(directory)


@pytest.fixture
def report_config(monkeypatch):
    for name in ('REPORT_BILINGUAL', 'REPORT_STRUCTURED_FORECAST', 'REPORT_FORECAST_LEDGER',
                 'REPORT_VISUALIZATIONS', 'REPORT_SECTION_REFLECTION', 'REPORT_PUBLISH_GATE',
                 'REPORT_LANGUAGE_PURITY',
                 'REPORT_THREE_PART_SKELETON', 'REPORT_SECTION_CONTINUE', 'REPORT_TELEMETRY'):
        monkeypatch.setattr(Config, name, False, raising=False)
    monkeypatch.setattr(Config, 'REPORT_CITATION_FINALIZER', True)
    monkeypatch.setattr(Config, 'REPORT_EDITORIAL_LINT', True)
    monkeypatch.setattr(Config, 'REPORT_SECTION_CONCURRENCY', 1)
    monkeypatch.setattr(Config, 'REPORT_SIGNAL_PACK', True)
    monkeypatch.setattr(ReportAgent, 'MIN_TOOL_CALLS_PER_SECTION', 0)
    monkeypatch.setattr(ReportAgent, 'OUTLINE_PAD_FLOOR_SECTIONS', 1)


class ReportModel(FakeLLMClient):
    def chat_json(self, messages, **kwargs):
        self.calls.append({'kind': 'chat_json', 'messages': messages})
        return {'title': 'Supply outlook', 'summary': 'The external research supports cautious planning.',
                'sections': [{'title': 'Supply and demand', 'description': 'Assess constraints.'}]}

    def chat(self, messages, **kwargs):
        self.calls.append({'kind': 'chat', 'messages': messages})
        return 'Final Answer: ' + ' '.join(
            f'{word} depends on observed conditions and documented institutional constraints. '
            'A decision requires checking the underlying evidence and the scope of the relevant mandate.'
            for word in ('Investment', 'Supply', 'Demand', 'Competition', 'Financing', 'Planning',
                         'Production', 'Distribution', 'Procurement', 'Trade', 'Coordination', 'Execution'))


def generate(directory, report_id='report_world', **kwargs):
    model = kwargs.pop('llm_client', ReportModel())
    a = agent(directory, research_report='EXTERNAL_EVIDENCE: documented capacity observations.',
              llm_client=model, **kwargs)
    report = a.generate_report(report_id=report_id)
    assert report.status.value == 'completed', report.error
    return a, report, model


@pytest.mark.parametrize('domain', ['investment', 'trade', 'coalition'])
def test_real_generation_copies_exact_result_and_conditional_pathway(world, report_config, domain):
    directory = world(domain)
    a, report, model = generate(directory)
    owned = ReportManager.load_world_result(report.report_id)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    for name in ('world_result.json', 'world_result_manifest.json'):
        assert (folder / name).read_bytes() == (directory / name).read_bytes()
    assert owned['reference'] == report.world_result_ref
    assert '## Conditional world pathway' in report.markdown_content
    assert owned['result']['horizon'] in report.markdown_content
    assert owned['result']['revision'] in report.markdown_content
    assert ReportManager.publication_status(report.report_id)['publishable']
    assert model.calls
    assert a._execute_tool('interview_agents', {}) .startswith('Unsupported')


def test_no_update_keeps_ui_result_but_excludes_all_world_reasoning(world, report_config, monkeypatch):
    directory = world(effect='no_update')
    monkeypatch.setattr(Config, 'SIMULATION_FORECAST_EFFECT', 'legacy_prompt')
    a, report, model = generate(directory)
    result = ReportManager.load_world_result(report.report_id)['result']
    assert result['trajectory']
    assert 'Conditional world pathway' not in report.markdown_content
    assert a._build_signal_pack() == ''
    assert 'world_pathway' not in a.tools
    assert a._execute_tool('world_pathway', {}) == ''
    actual_prompts = json.dumps(model.calls)
    assert result['revision'] not in actual_prompts
    assert 'goods_per_day' not in actual_prompts


@pytest.mark.parametrize('target', ['world_generation_id', 'world_spec_sha256', 'world_input_manifest_sha256'])
def test_constructor_rejects_saved_input_pin_mismatch(world, target):
    directory = world()
    state = json.loads((directory / 'state.json').read_text())
    state[target] = 'wrong'
    atomic_json(directory / 'state.json', state)
    with pytest.raises(WorldError):
        agent(directory)


@pytest.mark.parametrize('target', ['world_result.json', 'world_result_manifest.json', 'world_result_ref.json', 'meta.json'])
def test_all_public_consumers_reject_tampered_binding(world, report_config, target):
    from app.services.report_visualizer import ReportVisualizer
    directory = world()
    a, report, _ = generate(directory)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    if target == 'meta.json':
        data = json.loads((folder / target).read_text())
        data['world_result_ref']['revision'] = 'wrong'
        atomic_json(folder / target, data)
    else:
        (folder / target).write_bytes((folder / target).read_bytes() + b' ')
        if target == 'world_result_ref.json':
            atomic_json(folder / target, {'revision': 'wrong'})
    assert not ReportManager.publication_status(report.report_id)['publishable']
    with pytest.raises(WorldError):
        ReportManager.get_report(report.report_id)
    with pytest.raises(WorldError):
        a.chat('Explain the result')
    with pytest.raises(WorldError):
        ReportVisualizer().build_all(report.report_id, str(folder), {})
    translator = FakeLLMClient()
    with pytest.raises(WorldError):
        ReportManager.generate_translation_variant(report.report_id, 'zh', llm_client=translator)
    assert translator.calls == []
    assert ReportManager.export_pdf(report.report_id) is None


def test_producer_tampering_invalidates_cached_chat_and_does_not_repair(world, report_config):
    directory = world()
    a, report, model = generate(directory)
    a.chat('First question')
    before = len(model.calls)
    source = directory / 'world_result.json'
    source.write_bytes(source.read_bytes() + b' ')
    damaged = source.read_bytes()
    with pytest.raises(WorldError):
        a.chat('Cached question')
    with pytest.raises(WorldError):
        agent(directory)
    assert len(model.calls) == before
    assert source.read_bytes() == damaged


def test_chart_public_builder_uses_bound_result_and_native_units(world, report_config, monkeypatch):
    from app.services.report_visualizer import ReportVisualizer
    directory = world()
    a, report, _ = generate(directory)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    monkeypatch.setattr(Config, 'REPORT_VIZ_INTERACTIVE', False, raising=False)
    monkeypatch.setattr(Config, 'REPORT_VIZ_CHARTS', False, raising=False)
    viz = ReportVisualizer()
    items = viz.build_all(report.report_id, str(folder), {})
    charts = [item for item in items if item['source'] == 'world_result']
    assert len(charts) == 2
    item = next(row for row in charts if row['metric_id'] == 'capacity')
    assert item['unit'] == 'goods_per_day'
    svg = (folder / item['path']).read_text()
    assert '4 goods_per_day' in svg and '7 goods_per_day' in svg
    assert ReportManager.load_world_result(report.report_id)['result']['trajectory'][0]['simulatedAt'] in svg
    assert item['world_result_ref'] == report.world_result_ref
    wrong = dict(ReportManager.load_world_result(report.report_id)['result'], revision='wrong')
    with pytest.raises(WorldError):
        viz.build_all(report.report_id, str(folder), {'world_result': wrong})


class ForecastModel(FakeLLMClient):
    def chat_json(self, messages, **kwargs):
        self.calls.append({'kind': 'probability', 'messages': messages})
        if getattr(self, 'fail_spine', False) and len(self.calls) == 1:
            return {}
        return {'headline': 'Evidence outlook', 'confidence': 'low', 'scenarios': [
            {'name': 'Expansion', 'probability': .6, 'description': 'External evidence',
             'resolution_criteria': 'Expansion is measured by the horizon.'},
            {'name': 'Status quo', 'probability': .4, 'description': 'External evidence',
             'resolution_criteria': 'Expansion is not measured by the horizon.'}],
            'binary_forecasts': []}


@pytest.mark.parametrize('spine', [True, False, 'failed'])
@pytest.mark.parametrize('effect', ['diagnostic_only', 'no_update'])
@pytest.mark.parametrize('research', [True, False])
def test_forecast_model_bytes_invariant_to_trajectory_including_fallbacks(
        tmp_path, monkeypatch, world, spine, effect, research):
    # Two full real runs differ in capacity; the external evidence is identical.
    # Each probability extractor, binary top-up/repair and critique executes for real.
    monkeypatch.setattr(Config, 'SIMULATION_FORECAST_EFFECT', 'legacy_prompt')
    monkeypatch.setattr(Config, 'REPORT_FORECAST_LEDGER', False)
    monkeypatch.setattr(Config, 'REPORT_FORECAST_SELF_CRITIQUE', True)
    monkeypatch.setattr(Config, 'FORECAST_EMIT_BINARY', True)
    monkeypatch.setattr(Config, 'FORECAST_BINARY_MIN_COUNT', 1, raising=False)
    monkeypatch.setattr(Config, 'REPORT_REPAIR_PASSES', True)
    monkeypatch.setattr(Config, 'REPORT_CITATION_REPAIR', False)
    captures = []
    for index, capacity in enumerate(('4', '5')):
        directory = world(effect=effect, capacity=capacity, identity=f'sim_pair_{index}')
        monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(directory.parent))
        model = ForecastModel()
        model.fail_spine = spine == 'failed'
        a = agent(directory, llm_client=model,
                  research_report='EXTERNAL_EVIDENCE only.' if research else '',
                  situation_brief='EXTERNAL_BRIEF retained without a research report.')
        rid = f'report_pair_{index}'
        ReportManager._ensure_report_folder(rid)
        a._signal_pack = a._build_signal_pack()
        if spine:
            a._derive_and_pin_forecast_spine(rid)
            if spine != 'failed':
                assert a._forecast_spine and a._forecast_spine['scenarios']
        a._finalize_structured_forecast(rid, f'SIMULATED_PROSE_{index} claims 99% growth.')
        probability_prompts = [call['messages'] for call in model.calls if call['kind'] == 'probability']
        assert len(probability_prompts) >= 2  # scenario + binary, including top-up
        assert 'SIMULATED_PROSE' not in json.dumps(probability_prompts)
        assert 'goods_per_day' not in json.dumps(probability_prompts)
        captures.append(probability_prompts)
    assert captures[0] == captures[1]


def test_missing_all_clean_evidence_fails_forecast_without_model_call(world, monkeypatch):
    directory = world()
    model = ForecastModel()
    a = agent(directory, llm_client=model)
    ReportManager._ensure_report_folder('report_missing')
    a._derive_and_pin_forecast_spine('report_missing')
    assert not a._forecast_spine
    with pytest.raises(WorldError, match='external research evidence'):
        a._finalize_structured_forecast('report_missing', 'SIMULATED_PROSE 90% probability')
    assert model.calls == []


def test_legacy_constructor_does_not_require_world_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    legacy = agent(tmp_path / 'sim_legacy')
    assert legacy._world_binding is None
    assert legacy._probability_source('legacy prose') == 'legacy prose'


@pytest.fixture
def report_client(monkeypatch, tmp_path):
    from flask import Flask
    from app.api import report_bp
    from app.api import report as api
    monkeypatch.setattr(api.ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'projects'))
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(report_bp, url_prefix='/api/report')
    return app.test_client()


def test_report_routes_share_pin_and_reject_before_export_or_translation(
        world, report_config, report_client):
    directory = world()
    _, report, _ = generate(directory)
    rid = report.report_id
    response = report_client.get(f'/api/report/{rid}/world-result')
    assert response.status_code == 200
    assert response.get_json()['data']['reference'] == report.world_result_ref
    assert report_client.get(f'/api/report/{rid}/download').status_code == 200
    source = directory / 'world_result.json'
    source.write_bytes(source.read_bytes() + b' ')
    for route in (rid, rid + '/world-result', rid + '/download', rid + '/forecast',
                  rid + '/pdf', rid + '/viz-manifest', rid + '/charts/example.svg',
                  rid + '/full_report.zh.md'):
        response = report_client.get('/api/report/' + route)
        assert response.status_code == 409, (route, response.get_json())
    assert report_client.post(f'/api/report/{rid}/translations/zh').status_code == 409
    for force in (False, True):
        assert report_client.post('/api/report/generate', json={
            'simulation_id': directory.name, 'force_regenerate': force}).status_code == 409
    assert report_client.post('/api/report/chat', json={
        'simulation_id': directory.name, 'message': 'Explain'}).status_code == 409



def test_report_telemetry_floats_in_meta_keep_world_reports_readable(world, report_config, report_client):
    """Report telemetry writes floats into meta.json (the report's own record, not a world
    artefact); the binding still verifies and the gated routes still serve.  Tampering with
    the identity meta.json names still fails closed."""
    directory = world()
    _, report, _ = generate(directory)
    rid = report.report_id
    folder = Path(ReportManager._get_report_folder(rid))
    data = json.loads((folder / 'meta.json').read_text())
    data['telemetry'] = {'totals': {'duration_s': 812.4, 'est_cost_usd': 0.4213, 'latency_ms': 2311.7}}
    (folder / 'meta.json').write_text(json.dumps(data))
    owned = ReportManager.load_world_result(rid)
    assert owned is not None and owned['reference'] == report.world_result_ref
    for route in (rid, rid + '/world-result', rid + '/download'):
        assert report_client.get('/api/report/' + route).status_code == 200, route
    data['world_result_ref']['revision'] = 'wrong'
    (folder / 'meta.json').write_text(json.dumps(data))
    with pytest.raises(WorldError):
        ReportManager.load_world_result(rid)
    assert report_client.get(f'/api/report/{rid}').status_code == 409

def test_direct_generation_and_regeneration_use_real_constructor(world, report_config, report_client, monkeypatch):
    import time
    from app.api import report as api
    from app.services import report_agent as module
    directory = world()
    monkeypatch.setattr(api.SimulationManager, 'SIMULATION_DATA_DIR', str(directory.parent))
    project = api.ProjectManager.create_project('World fixture')
    project.graph_id = 'graph_test'
    project.simulation_requirement = 'Write an English supply outlook.'
    api.ProjectManager.save_project(project)
    state = json.loads((directory / 'state.json').read_text())
    state.update(project_id=project.project_id, graph_id=project.graph_id)
    atomic_json(directory / 'state.json', state)
    models = []
    def make_model(*args, **kwargs):
        model = ReportModel()
        models.append(model)
        return model
    monkeypatch.setattr(module, 'LLMClient', make_model)
    ids = []
    for force in (False, True):
        response = report_client.post('/api/report/generate', json={
            'simulation_id': directory.name, 'force_regenerate': force})
        assert response.status_code == 200, response.get_json()
        rid = response.get_json()['data']['report_id']
        ids.append(rid)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            progress = ReportManager.get_progress(rid) or {}
            if progress.get('status') in {'completed', 'failed'}:
                break
            time.sleep(.02)
        report = ReportManager.get_report(rid)
        assert report and report.status.value == 'completed', progress
        assert ReportManager.load_world_result(rid)['reference'] == report.world_result_ref
    assert ids[0] != ids[1]
    response = report_client.post('/api/report/chat', json={
        'simulation_id': directory.name, 'message': 'Explain the capacity pathway'})
    assert response.status_code == 200, response.get_json()
    assert 'goods_per_day' in json.dumps(models[-1].calls)


def test_horizon_pending_obligations_are_not_reported_as_settled(world, report_config):
    directory = world(periods=1)
    _, report, _ = generate(directory)
    result = ReportManager.load_world_result(report.report_id)['result']
    assert result['completed'] is True
    pending = [record for record in result['world']['commitments'].values() if record['status'] == 'pending']
    assert pending
    assert '"status": "pending"' in report.markdown_content
    assert result['world']['metrics']['capacity']['value'] == '4'


def test_world_pin_cannot_downgrade_to_legacy(world):
    directory = world()
    state = json.loads((directory / 'state.json').read_text())
    state.pop('simulation_engine')
    atomic_json(directory / 'state.json', state)
    with pytest.raises(WorldError, match='engine pin'):
        agent(directory)


def test_categorical_metric_preserves_numeric_charts(world, report_config, monkeypatch):
    from app.services.report_visualizer import ReportVisualizer
    directory = world(category=True)
    _, report, _ = generate(directory)
    monkeypatch.setattr(Config, 'REPORT_VIZ_INTERACTIVE', False, raising=False)
    monkeypatch.setattr(Config, 'REPORT_VIZ_CHARTS', False, raising=False)
    items = ReportVisualizer().build_all(report.report_id, ReportManager._get_report_folder(report.report_id), {})
    assert {row['metric_id'] for row in items if row['source'] == 'world_result'} == {'capacity', 'input_limit'}
    assert '| `access` | `open` | `status` |' in report.markdown_content


@pytest.mark.parametrize('damage', ['asset', 'manifest'])
def test_chart_bytes_and_provenance_rejected_at_public_routes_and_pdf(
        world, report_config, report_client, monkeypatch, damage):
    from app.services.report_visualizer import ReportVisualizer
    directory = world()
    a, report, _ = generate(directory)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    monkeypatch.setattr(Config, 'REPORT_VIZ_INTERACTIVE', False, raising=False)
    monkeypatch.setattr(Config, 'REPORT_VIZ_CHARTS', False, raising=False)
    items = ReportVisualizer().build_all(report.report_id, str(folder), {})
    a._audit_final_published_markdown(report.report_id, report)
    chart = next(row for row in items if row['source'] == 'world_result')
    url = f'/api/report/{report.report_id}/' + chart['path']
    assert report_client.get(url).status_code == 200
    if damage == 'asset':
        (folder / chart['path']).write_text('<svg>another world</svg>')
    else:
        path = folder / 'viz_manifest.json'
        data = json.loads(path.read_text())
        data['provenance']['world_result_ref']['revision'] = 'other-world'
        atomic_json(path, data)
    assert report_client.get(url).status_code == 409
    assert report_client.get(f'/api/report/{report.report_id}/viz-manifest').status_code == 409
    assert ReportManager.export_pdf(report.report_id) is None


def test_invalid_world_report_does_not_block_unrelated_legacy_lookup(world, report_config):
    from app.services.report_agent import Report, ReportStatus
    directory = world()
    _, report, _ = generate(directory)
    legacy = Report('report_legacy', 'sim_legacy', 'graph', 'Question', ReportStatus.COMPLETED,
                    markdown_content='Legacy body', created_at='2020-01-01')
    ReportManager.save_report(legacy)
    (directory / 'world_result.json').unlink()
    Path(ReportManager._get_sim_index_path()).unlink()
    assert ReportManager.get_report_by_simulation('sim_legacy').report_id == 'report_legacy'
    assert [r.report_id for r in ReportManager.list_reports()] == ['report_legacy']
    with pytest.raises(WorldError):
        ReportManager.get_report(report.report_id)


def test_probability_synthesis_and_prose_repairs_do_not_receive_world_diagnostics(world, report_config):
    directory = world()
    a, report, model = generate(directory)
    # The exact world appendix is materialized after prose finalization. No model
    # authoring/repair call sees it, so legacy editing cannot launder attribution.
    assert 'goods_per_day' not in json.dumps(model.calls)
    assert 'conditional_world_pathway' not in json.dumps(model.calls)
    assert 'goods_per_day' in report.markdown_content
    before = len(model.calls)
    a._build_part2_synthesis('SIMULATED_PROSE: capacity reaches 999 goods_per_day.')
    assert len(model.calls) == before + 1
    assert 'SIMULATED_PROSE' not in json.dumps(model.calls[-1])
    assert 'EXTERNAL_EVIDENCE' in json.dumps(model.calls[-1])


def test_translation_real_public_consumer_retains_world_binding(world, report_config, monkeypatch):
    from tests.test_report_forecast_localization import Translator
    directory = world()
    _, report, _ = generate(directory)
    translator = Translator()
    monkeypatch.setattr(Config, 'REPORT_BILINGUAL', True)
    status = ReportManager.generate_translation_variant(report.report_id, 'zh', llm_client=translator)
    assert translator.calls > 0
    assert status['available'], status
    folder = Path(ReportManager._get_report_folder(report.report_id))
    audit = json.loads((folder / 'final_audit.zh.json').read_text())
    assert audit['world_result_ref'] == report.world_result_ref
    assert ReportManager.publication_status(report.report_id, 'zh')['publishable']


def test_public_pdf_export_binds_world_reference_and_rechecks_cached_export(world, report_config, monkeypatch):
    import textwrap
    import fitz
    directory = world(effect='no_update')
    _, report, _ = generate(directory)
    renders = []
    # Only the external rendering boundary is substituted; the real PDF content,
    # publication, dependency and cache verification all run.
    def render(cls, report_id, markdown, folder, pdf_path):
        renders.append(report_id)
        lines = textwrap.wrap(cls._markdown_visible_text(markdown), width=90)
        doc = fitz.open()
        for index in range(0, len(lines), 48):
            page = doc.new_page()
            page.insert_text((48, 48), '\n'.join(lines[index:index + 48]), fontsize=9)
        doc.save(pdf_path)
        doc.close()
        return True
    monkeypatch.setattr(ReportManager, '_export_pdf_pandoc', classmethod(render))
    monkeypatch.setattr(ReportManager, '_pdf_renderer_fingerprint', classmethod(lambda cls: {'renderer': 'fixture'}))
    path = ReportManager.export_pdf(report.report_id)
    assert path and Path(path).is_file()
    manifest = json.loads(Path(ReportManager._get_report_pdf_manifest_path(report.report_id)).read_text())
    assert manifest['input']['world_result_ref'] == report.world_result_ref
    assert ReportManager.export_pdf(report.report_id) == path
    assert renders == [report.report_id]
    (directory / 'world_result.json').write_bytes(b'{}')
    assert ReportManager.export_pdf(report.report_id) is None
    assert renders == [report.report_id]


def test_chat_then_regenerate_on_same_agent_restores_evidence_only_tools(world, report_config):
    directory = world()
    a, _, model = generate(directory)
    a.chat('Describe the simulated pathway')
    assert 'world_pathway' in a.tools
    start = len(model.calls)
    report = a.generate_report(report_id='report_after_chat')
    assert report.status.value == 'completed', report.error
    assert 'world_pathway' not in a.tools
    assert 'goods_per_day' not in json.dumps(model.calls[start:])
    assert 'goods_per_day' in report.markdown_content


def test_chart_route_rejects_unlisted_asset_and_seals_inlined_dependency(
        world, report_config, report_client, monkeypatch):
    from app.services.report_visualizer import ReportVisualizer
    directory = world()
    a, report, _ = generate(directory)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    # A fake HTML renderer exercises real build_all manifest binding and the
    # actual serve-time script inliner; no plotting subprocess is needed.
    def render(self, forecast, charts_dir, **kwargs):
        path = Path(charts_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / 'scenario_probabilities.html').write_text('<html><script src="plotly.min.js"></script></html>')
        (path / 'plotly.min.js').write_text('window.fixture = 1;')
        return 'charts/scenario_probabilities.html'
    monkeypatch.setattr(ReportVisualizer, 'build_scenario_bars_html', render)
    monkeypatch.setattr(ReportVisualizer, '_interactive_ok', staticmethod(lambda: True))
    monkeypatch.setattr(Config, 'REPORT_VIZ_CHARTS', False, raising=False)
    monkeypatch.setattr(Config, 'REPORT_VIZ_PNG_EXPORT', False, raising=False)
    items = ReportVisualizer().build_all(report.report_id, str(folder), {
        'forecast': {'scenarios': [{'name': 'A', 'probability': .6}, {'name': 'B', 'probability': .4}]}})
    item = next(item for item in items if item['id'] == 'scenario_probabilities')
    assert 'charts/plotly.min.js' in item['artifact_sha256']
    a._audit_final_published_markdown(report.report_id, report)
    url = f'/api/report/{report.report_id}/charts/scenario_probabilities.html'
    response = report_client.get(url)
    assert response.status_code == 200
    assert 'window.fixture = 1;' in response.get_data(as_text=True)
    (folder / 'charts/unlisted.svg').write_text('<svg>wrong world</svg>')
    assert report_client.get(f'/api/report/{report.report_id}/charts/unlisted.svg').status_code == 404
    (folder / 'charts/plotly.min.js').write_text('window.fixture = 2;')
    assert report_client.get(url).status_code == 409
