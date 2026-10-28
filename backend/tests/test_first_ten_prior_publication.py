"""The final publication audit cannot seal a stale prior/posterior ledger."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services.forecast_extractor import validate_prior_posterior_updates
from tests.test_final_publish_audit import _agent, _prepare, _forecast


@pytest.mark.parametrize('tamper', [False, True])
def test_final_audit_validates_prior_ledger_without_repair(monkeypatch, tmp_path, tamper):
    monkeypatch.setattr(Config, 'REPORT_PUBLISH_GATE_MODE', 'grade')
    source = {'title': 'Official outlook', 'url': 'https://example.gov/outlook', 'date': '2026-06-30',
              'tier': 'S1', 'content': 'Revenue could reach 65% by 2030 according to the official source.'}
    report = SimpleNamespace(markdown_content='# Forecast\n\nRevenue could reach 65% by 2030 [S1].\n')
    folder = Path(_prepare(monkeypatch, tmp_path, 'report_prior_final', report.markdown_content))
    forecast = _forecast()
    prior = {'scenarioWeights': {row['name']: row['probability'] for row in forecast['scenarios']}, 'asOf': '2026-10-27'}
    validate_prior_posterior_updates(forecast, prior, [
        {'name': row['name'], 'prior': row['probability'], 'posterior': row['probability'], 'reason': ''}
        for row in forecast['scenarios']])
    if tamper:
        forecast['scenario_updates'][0]['posterior'] = 0.5
    original_ledger = deepcopy(forecast['scenario_updates'])
    (folder / 'forecast.json').write_text(json.dumps(forecast))
    agent = _agent(source)
    agent._finalize_citations('report_prior_final', report)
    audit = agent._audit_final_published_markdown('report_prior_final', report)
    assert audit['structured_forecast']['research_prior']['valid'] is not tamper
    if tamper:
        assert not audit['hard_passed']
    assert json.loads((folder / 'forecast.json').read_text())['scenario_updates'] == original_ledger
