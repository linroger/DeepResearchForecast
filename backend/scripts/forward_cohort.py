#!/usr/bin/env python3
"""Validate a frozen prospective candidate set; never submit or schedule runs.

Usage: forward_cohort.py propose --dry-run --candidates candidates.json --as-of YYYY-MM-DD
Dates and settlement contracts must come from the candidate file. This command
checks the existing forward protocol; it does not invent release calendars.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path


def propose(candidates, *, as_of):
    from backtest_eval import check_forward_question, forward_prompt
    cutoff = date.fromisoformat(as_of)
    rows = candidates.get('questions') if isinstance(candidates, dict) else candidates
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('candidates must contain at most 1000 questions')
    accepted, rejected, seen = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('candidate must be an object')
        problems = check_forward_question(row)
        if row.get('example'):
            problems.append('template examples are not enrollment candidates')
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier.strip():
            problems.append('candidate identity must be a nonempty string')
        elif identifier in seen:
            problems.append('duplicate candidate identity')
        else:
            seen.add(identifier)
        if row.get('asked_on') != cutoff.isoformat():
            problems.append('asked_on must equal the proposed cohort cutoff')
        if any(key in row for key in ('outcome', 'resolved', 'score', 'answer', 'actual')):
            problems.append('outcome-bearing candidate is not prospective')
        source = row.get('resolution_source') if isinstance(row.get('resolution_source'), dict) else {}
        if source.get('kind') == 'official_data':
            threshold = source.get('threshold')
            if type(threshold) not in (int, float) or not math.isfinite(threshold):
                problems.append('official threshold must be finite')
        if problems:
            rejected.append({'id': row.get('id'), 'issues': problems})
            continue
        accepted.append({'question': json.loads(json.dumps(row, allow_nan=False)), 'prompt': forward_prompt(row)})
    encoded = json.dumps(accepted, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return {'schemaVersion': 'forward-cohort-proposal/v1', 'asOf': as_of,
            'dryRun': True, 'enrolled': False, 'paidRunsStarted': 0,
            'candidateHash': hashlib.sha256(encoded.encode()).hexdigest(),
            'questions': accepted, 'rejected': rejected,
            'validationLimit': 'Source release schedules and live availability are not verified by this offline check.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['propose'])
    parser.add_argument('--dry-run', action='store_true', required=True)
    parser.add_argument('--candidates', required=True, type=Path)
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args(argv)
    try:
        result = propose(json.loads(args.candidates.read_text()), as_of=args.as_of)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 1 if result['rejected'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
