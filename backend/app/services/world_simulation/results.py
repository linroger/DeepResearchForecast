"""One committed world result for API, report, charts and export consumers."""
from __future__ import annotations

from pathlib import Path

from .artifacts import atomic_json, file_digest, load_inputs, read_json
from .contracts import ENGINE, RESULT_SCHEMA, clone, digest, parse_time, require, visible_to
from .store import WorldStore


def _delivered(interaction, at, view, actor_id):
    # Senders know their own queued messages/offers; recipients and the public
    # gain that context only at delivery, including in historical projections.
    return (view == 'analyst' or actor_id == interaction.get('proposerId')
            or parse_time(interaction['deliverAt']) <= parse_time(at))


def _event_visible(event, snapshot, view, actor_id):
    if not visible_to(event, actor_id, view=view):
        return False
    interaction = snapshot['interactions'].get(event.get('details', {}).get('interactionId'))
    if interaction is not None and event['kind'] == 'offer_counter':
        interaction = snapshot['interactions'].get(interaction.get('supersededBy'), interaction)
    return interaction is None or _delivered(interaction, snapshot['simulatedAt'], view, actor_id)


def _project(snapshot, view, actor_id):
    result = {'round': snapshot['round'], 'simulatedAt': snapshot['simulatedAt']}
    for section in ('accounts', 'metrics', 'rules', 'relations', 'commitments', 'interactions'):
        result[section] = {key: clone(record) for key, record in snapshot[section].items()
                           if visible_to(record, actor_id, view=view)
                           and (section != 'interactions'
                                or _delivered(record, snapshot['simulatedAt'], view, actor_id))}
        if snapshot['round'] > 0:
            for record in result[section].values():
                record['initialBasis'] = clone(record.get('basis'))
                record['basis'] = {'kind': 'simulation_event',
                    'refs': [f"world:{snapshot['simulationId']}:round:{snapshot['round']}"]}
                if record.get('valueStatus') != 'unknown':
                    record['valueStatus'] = 'simulated'
    if view == 'analyst':
        result['actorStates'] = clone(snapshot['actorStates'])
    elif actor_id is not None:
        result['actorState'] = clone(snapshot['actorStates'][actor_id])
    return result


def read_result(directory: Path, *, view='public', actor_id=None, round_index=None, revision=None) -> dict:
    require(view in {'public', 'actor', 'analyst'}, 'invalid_view', 'Unknown world projection')
    require(view == 'actor' or actor_id is None, 'invalid_view', 'Actor identity belongs only to the actor view')
    spec, manifest = load_inputs(directory)
    require(view != 'actor' or actor_id in {a['actorId'] for a in spec['actors']},
            'unknown_actor', 'Actor view requires an admitted actor')
    with WorldStore(Path(directory) / 'world.sqlite3', spec, read_only=True) as store:
        bundle = store.read_bundle()
    return _render_bundle(bundle, view=view, actor_id=actor_id, round_index=round_index, revision=revision)


def _render_bundle(bundle, *, view='public', actor_id=None, round_index=None, revision=None):
    spec = bundle['spec']
    head = bundle['head']
    require(revision is None or revision == head['revision'], 'stale_revision', 'Committed world changed; refresh the view')
    selected = head['round'] if round_index is None else round_index
    require(type(selected) is int and 0 <= selected <= head['round'], 'invalid_round', 'Round has not been committed')
    history = bundle['history'][:selected + 1]
    rounds = [row for row in bundle['rounds'] if row['round'] <= selected]
    events = [event for event in history[0].get('initialEvents', [])
              if _event_visible(event, history[-1], view, actor_id)]
    events.extend(event for row in rounds for event in row['events']
                  if _event_visible(event, history[-1], view, actor_id))
    decisions = [clone(d) for row in rounds for d in row['decisions']
                 if view == 'analyst' or (view == 'actor' and d['actorId'] == actor_id)]
    resolutions = [clone(r) for row in rounds for r in row['resolutions']
                   if view == 'analyst' or (view == 'actor' and r['actorId'] == actor_id)]
    result = {'schemaVersion': RESULT_SCHEMA, 'engine': ENGINE, 'simulationId': spec['simulationId'],
              'generationId': spec['generationId'], 'revision': head['revision'],
              'selectedRevision': history[-1]['revision'], 'specHash': digest(spec),
              'forecastEffect': spec['forecastEffect'], 'completed': head['round'] == len(spec['periods']),
              'round': selected, 'committedRound': head['round'], 'totalRounds': len(spec['periods']),
              'asOf': spec['asOf'], 'horizon': spec['horizon'], 'view': view, 'actorId': actor_id,
              'valueStatus': 'simulated', 'world': _project(history[-1], view, actor_id),
              'trajectory': [_project(row, view, actor_id) for row in history],
              'events': clone(events), 'decisions': decisions, 'resolutions': resolutions,
              'interpretation': 'Conditional pathway under declared assumptions; not a calibrated probability forecast.'}
    if view == 'analyst':
        result.update(assumptions=clone(spec['assumptions']), sourceBindings=clone(spec['sourceBindings']),
                      budget=clone(bundle['budget']))
    else:
        result['assumptions'] = [clone(a) for a in spec['assumptions'] if visible_to(a, actor_id)]
    return result


def validate_recoverable_export(directory: Path) -> None:
    """Both export pieces must independently match a committed revision.

    A crash can leave result N with manifest N-1. Accept that explicit recovery
    case, while rejecting modified content that never appeared in SQLite.
    """
    directory = Path(directory)
    spec, _ = load_inputs(directory)
    with WorldStore(directory / 'world.sqlite3', spec, read_only=True) as store:
        bundle = store.read_bundle()
    results, manifests = [], []
    for snapshot in bundle['history']:
        round_index = snapshot['round']
        prefix = {**bundle, 'head': snapshot, 'history': bundle['history'][:round_index + 1],
                  'rounds': [r for r in bundle['rounds'] if r['round'] <= round_index]}
        result = _render_bundle(prefix)
        results.append(result)
        import hashlib
        from .contracts import canonical_json
        manifests.append({'schemaVersion': 'world-result-manifest/v1', 'engine': ENGINE,
            'simulationId': result['simulationId'], 'generationId': result['generationId'],
            'revision': result['revision'], 'specHash': result['specHash'],
            'resultSha256': hashlib.sha256((canonical_json(result) + '\n').encode('utf-8')).hexdigest(),
            'resultHash': digest(result)})
    for filename, expected in [('world_result.json', results), ('world_result_manifest.json', manifests)]:
        path = directory / filename
        if path.exists():
            allowed_bytes = {hashlib.sha256((canonical_json(item) + '\n').encode('utf-8')).hexdigest()
                             for item in expected}
            require(read_json(path) in expected and file_digest(path) in allowed_bytes, 'result_binding_mismatch',
                    'Existing result artifact is not a projection of any committed revision')


def export_result(directory: Path) -> dict:
    """Explicit writer operation; GET/read_result never repairs derived files."""
    directory = Path(directory)
    result = read_result(directory)
    path = directory / 'world_result.json'
    atomic_json(path, result)
    manifest = {'schemaVersion': 'world-result-manifest/v1', 'engine': ENGINE,
                'simulationId': result['simulationId'], 'generationId': result['generationId'],
                'revision': result['revision'], 'specHash': result['specHash'],
                'resultSha256': file_digest(path), 'resultHash': digest(result)}
    atomic_json(directory / 'world_result_manifest.json', manifest)
    return manifest


def load_frozen_result(directory: Path, *, require_complete=True) -> dict:
    directory = Path(directory)
    spec, _ = load_inputs(directory)
    result = read_json(directory / 'world_result.json')
    manifest = read_json(directory / 'world_result_manifest.json')
    require(manifest.get('schemaVersion') == 'world-result-manifest/v1' and manifest.get('engine') == ENGINE,
            'result_binding_mismatch', 'Unknown world result binding')
    require(file_digest(directory / 'world_result.json') == manifest.get('resultSha256')
            and digest(result) == manifest.get('resultHash'), 'result_binding_mismatch', 'Consumed world result bytes changed')
    current = read_result(directory)
    require(result == current and manifest.get('revision') == current['revision']
            and manifest.get('specHash') == digest(spec) and manifest.get('simulationId') == spec['simulationId']
            and manifest.get('generationId') == spec['generationId'],
            'result_binding_mismatch', 'World result is stale or belongs to another generation')
    require(not require_complete or result['completed'], 'world_incomplete', 'World horizon is not committed')
    return result


def report_context(result: dict) -> dict:
    """Safe policy projection shared by every report consumer."""
    require(result.get('schemaVersion') == RESULT_SCHEMA, 'invalid_result', 'World result contract required')
    require(result.get('forecastEffect') in {'diagnostic_only', 'no_update'}, 'unsupported_policy', 'Unknown forecast policy')
    if result['forecastEffect'] == 'no_update':
        return {}
    return {'kind': 'conditional_world_pathway', 'probabilityEvidence': False, 'result': clone(result)}
