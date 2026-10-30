"""Known model contradictions cannot pass actual target pipeline/report admission."""
import json
from pathlib import Path

import pytest

from app.services.target_report import build_target_report
from app.services.target_simulation import run_paths
from tests import test_target_pipeline as pipeline_cases

case = pipeline_cases.case
runtime = pipeline_cases.runtime
execution = pipeline_cases.execution


@pytest.mark.parametrize('field,value', [('units', 'USD million'), ('units', 'EUR billion'), ('value', 290.0)])
def test_pipeline_rejects_known_contradiction_before_publication(execution, field, value):
    name = 'base' if field == 'units' else 'spending'
    next(row for row in execution.case['nodes'] if row['nodeId'] == name)[field] = value
    state = pipeline_cases._execute(execution)
    assert state.status == 'failed'
    assert 'model admission' in state.error
    assert state.report_id is None and state.simulation_id is None
    assert state.stages['research'].status != 'completed'


def test_report_consumer_rejects_legacy_unvalidated_bad_model(case):
    next(row for row in case['nodes'] if row['nodeId'] == 'base')['units'] = 'USD million'
    simulation = run_paths(case, paths=1, periods=1)  # Diagnostic helper deliberately retains its off mode.
    with pytest.raises(ValueError, match='model admission'):
        build_target_report(case, simulation)


def test_real_pipeline_seals_model_diagnostics_and_reports_gaps(execution):
    next(row for row in execution.case['nodes'] if row['nodeId'] == 'spending')['value'] = None
    state = pipeline_cases._execute(execution)
    assert state.status == 'completed', state.error
    simulation = json.loads(Path(state.artifacts['target_simulation']).read_text())
    assert simulation['modelValidation']['policy'] == 'known-contradictions/v1'
    assert simulation['modelValidation']['status'] == 'unmeasured'
    folder = Path(execution.po.ReportManager._get_report_folder(state.report_id))
    record = json.loads((folder / 'target_report.json').read_text())
    assert record['modelValidation'] == simulation['modelValidation']
    assert 'unmeasured' in (folder / 'full_report.md').read_text()
    assert execution.po.ReportManager.publication_status(state.report_id)['publishable']
    assert all(pipeline_cases.tp.validate_stage(state, name) for name in state.stages)


def test_zero_admitted_decision_budget_publishes_holds_without_provider_calls(execution, monkeypatch):
    from app.utils import llm_client
    monkeypatch.setattr(execution.config, 'TARGET_DECISION_MAX_CALLS', 0)
    monkeypatch.setattr(execution.config, 'LLM_PROVIDER', 'deepseek')
    monkeypatch.setattr(execution.config, 'LLM_API_KEY', 'fixture-only')
    monkeypatch.setattr(llm_client, 'LLMClient', lambda: pytest.fail('zero-budget actor dispatched'))
    execution.case['actors'][0]['decisionRule']['kind'] = 'llm'
    state = pipeline_cases._execute(execution)
    assert state.status == 'completed', state.error
    simulation = json.loads(Path(state.artifacts['target_simulation']).read_text())
    assert simulation['decisionBudget'] == {'maximumRequests': 0, 'requests': 0, 'cacheHits': 0, 'exhausted': True}
    assert execution.po.ReportManager.publication_status(state.report_id)['publishable']


@pytest.mark.parametrize('mutation', ['unknown_policy', 'missing_policy', 'false_status', 'malformed'])
def test_present_model_receipt_cannot_downgrade_to_legacy(case, mutation):
    next(row for row in case['nodes'] if row['nodeId'] == 'spending')['value'] = None
    simulation = run_paths(case, paths=1, periods=1, model_validation='admission')
    if mutation == 'unknown_policy':
        simulation['modelValidation']['policy'] = 'changed-policy/v1'
        simulation['modelValidation']['status'] = 'passed'
    elif mutation == 'missing_policy':
        del simulation['modelValidation']['policy']
    elif mutation == 'false_status':
        simulation['modelValidation']['status'] = 'passed'
    else:
        simulation['modelValidation'] = ['passed']
    with pytest.raises(ValueError, match='model admission receipt'):
        build_target_report(case, simulation)


def test_legacy_diagnostic_receipt_keeps_actual_gaps_visible(case):
    next(row for row in case['nodes'] if row['nodeId'] == 'base')['units'] = 'unmodeled-unit'
    simulation = run_paths(case, paths=1, periods=1, model_validation='diagnostic')
    bundle = build_target_report(case, simulation)
    assert bundle['record']['modelValidation']['status'] == 'unsupported'
    assert 'Model validation' in bundle['markdown']
