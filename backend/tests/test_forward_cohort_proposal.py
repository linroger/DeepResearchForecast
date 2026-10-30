"""Frozen candidate validation does not create forecasts or infer source dates."""
import copy
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'scripts'))
    return importlib.import_module('forward_cohort')


@pytest.fixture
def candidates():
    # Deliberately controlled fixture calendars, not a statement of actual release dates.
    rows = []
    for i, series in enumerate(['fred:UNRATE', 'fred:CPIAUCSL', 'fred:PAYEMS',
                                'fred:DGS10', 'fred:T10Y2Y', 'fred:INDPRO']):
        rows.append({'id': f'fixture-{i}', 'question': f'Will {series} exceed its declared threshold?',
            'resolution_criteria': f'YES if {series}, 2026-11, first release, is >= {i + 1}.',
            'resolution_source': {'kind': 'official_data', 'series': series, 'observation': '2026-11',
                                  'comparator': '>=', 'threshold': i + 1, 'units': 'fixture native units'},
            'asked_on': '2026-10-27', 'resolution_date': '2026-12-15'})
    return {'questions': rows}


def test_six_frozen_candidates_propose_without_enrollment(module, candidates):
    result = module.propose(candidates, as_of='2026-10-27')
    assert len(result['questions']) == 6
    assert result['rejected'] == []
    assert result['paidRunsStarted'] == 0 and result['enrolled'] is False
    assert result == module.propose(candidates, as_of='2026-10-27')


def test_outcomes_duplicates_and_date_mismatch_are_not_selected(module, candidates):
    candidates['questions'][0]['outcome'] = True
    candidates['questions'][1]['asked_on'] = '2026-01-01'
    candidates['questions'].append(copy.deepcopy(candidates['questions'][2]))
    result = module.propose(candidates, as_of='2026-10-27')
    assert len(result['rejected']) == 3
    assert len(result['questions']) == 4


def test_cli_dry_run_is_required_and_reports_fixture_output(module, candidates, tmp_path, capsys):
    path = tmp_path / 'candidates.json'
    path.write_text(json.dumps(candidates))
    with pytest.raises(SystemExit):
        module.main(['propose', '--candidates', str(path), '--as-of', '2026-10-27'])
    assert module.main(['propose', '--dry-run', '--candidates', str(path), '--as-of', '2026-10-27']) == 0
    assert len(json.loads(capsys.readouterr().out)['questions']) == 6



def test_invalid_identity_and_source_shape_are_rejected_without_type_crash(module, candidates):
    candidates['questions'][0]['id'] = ['unhashable']
    candidates['questions'][1]['resolution_source'] = ['invalid']
    result = module.propose(candidates, as_of='2026-10-27')
    assert len(result['rejected']) == 2
    assert len(result['questions']) == 4


def test_proposal_detaches_frozen_candidate_rows(module, candidates):
    result = module.propose(candidates, as_of='2026-10-27')
    candidates['questions'][0]['resolution_source']['threshold'] = 999
    assert result['questions'][0]['question']['resolution_source']['threshold'] == 1
