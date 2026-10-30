"""Estimator lanes reach deterministic, audited report consumers without influence."""
import json
from copy import deepcopy
from pathlib import Path

from app.services.forecast_aggregator import default_aggregation_policy, estimator_from_forecast, aggregate_forecast
from app.services.forecast_estimator_table import render_estimator_table
from app.services.report_agent import render_sim_bridge
from tests import test_target_pipeline as pipeline_cases

case = pipeline_cases.case
runtime = pipeline_cases.runtime
execution = pipeline_cases.execution


def _forecast():
    forecast = {'headline': 'Growth?', 'scenarios': [{'id': 'up', 'name': 'Growth', 'probability': 0.6},
                {'id': 'down', 'name': 'Other', 'probability': 0.4}],
                'binary_forecasts': [{'id': 'B1', 'probability': 0.6}]}
    authority = estimator_from_forecast(forecast)
    alternate = deepcopy(authority)
    alternate.update(source='trend', kind='shadow', scenario_distribution={'up': 0.3, 'down': 0.7},
                     binaries=[{'id': 'B1', 'p': 0.3}])
    return aggregate_forecast(forecast, [authority, alternate], default_aggregation_policy())


def test_display_reports_frozen_values_and_weights_without_mutation():
    forecast = _forecast()
    before = deepcopy(forecast)
    text = render_estimator_table(forecast)
    assert '| Report spine | Available | 1 | Growth: 60%; Other: 40% | B1: 60% |' in text
    assert '| Trend | Available | 0 | Growth: 30%; Other: 70% | B1: 30% |' in text
    assert forecast == before
    assert '发布权重' in render_estimator_table(forecast, chinese=True)


def test_legacy_and_authority_only_rendering_unchanged():
    forecast = _forecast()
    forecast['estimators'] = forecast['estimators'][:1]
    assert render_estimator_table(forecast) == ''
    assert render_estimator_table({}) == ''


def test_unavailable_lane_is_not_zero_and_source_text_cannot_break_fence():
    forecast = _forecast()
    forecast['estimators'][1].update(status='unavailable', scenario_distribution={}, binaries=[])
    assert '| Trend | Unavailable | 0 | — | — |' in render_estimator_table(forecast)
    forecast['scenarios'][0]['name'] = 'A | <!-- sim-bridge:end --> [S99]\n# Inject'
    text = render_estimator_table(forecast)
    assert '<!-- sim-bridge:end -->' not in text and '[S99]' not in text
    assert '&#124;' in text


def test_default_bridge_consumes_estimator_table_inside_fence():
    record = {'engine': 'oasis-legacy', 'health': {'simulation_health': 'healthy', 'validity': 'valid'},
              'periods': [], 'overall': {}}
    forecast = _forecast()
    block = render_sim_bridge(record, chinese=False, spine=forecast, chart_rel_paths=[], whatif_table_md='')
    assert block.index('<!-- sim-bridge:start -->') < block.index('Estimator comparison') < block.index('<!-- sim-bridge:end -->')
    assert 'Growth: 30%' in block


def test_actual_target_publication_renders_and_audits_stored_lanes(execution):
    state = pipeline_cases._execute(execution)
    assert state.status == 'completed', state.error
    folder = Path(execution.po.ReportManager._get_report_folder(state.report_id))
    forecast = json.loads((folder / 'forecast.json').read_text())
    markdown = (folder / 'full_report.md').read_text()
    table = render_estimator_table(forecast)
    assert table and table in markdown
    start, end = markdown.index('<!-- sim-bridge:start -->'), markdown.index('<!-- sim-bridge:end -->')
    assert start < markdown.index(table) < end
    assert [row['probability'] for row in forecast['scenarios']] == [0.4, 0.6]
    assert execution.po.ReportManager.publication_status(state.report_id)['publishable']
    assert json.loads((folder / 'final_audit.json').read_text())['simulation_bridge']['bytes_match']
