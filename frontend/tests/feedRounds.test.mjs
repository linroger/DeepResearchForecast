import assert from 'node:assert/strict'
import test from 'node:test'

import { feedRequest, postPeriodNote, roundLabel, selectionFromPanel } from '../src/utils/feedRounds.js'

const rounds = [
  { round: 0, period_label: '', headline: '', posts: 2, comments: 0 },
  { round: 1, period_label: '2026-11', headline: '2026-11: 3 decisions', posts: 3, comments: 1 },
  { round: 2, period_label: '2026-12', headline: '', posts: 1, comments: 2 }
]

test('roundLabel prefers the period label and falls back honestly', () => {
  assert.equal(roundLabel(rounds, 1), '2026-11')
  assert.equal(roundLabel(rounds, '2'), '2026-12')
  assert.equal(roundLabel(rounds, 0), '#0')                       // no label recorded for that round
  assert.equal(roundLabel(rounds, 0, 'from server'), 'from server')
  assert.equal(roundLabel(rounds, 7), '#7')
  assert.equal(roundLabel(undefined, 'x'), '')
  assert.equal(roundLabel(null, NaN, 'f'), 'f')
})

test('selectionFromPanel normalises the emitted selection', () => {
  assert.equal(selectionFromPanel(null), null)
  assert.equal(selectionFromPanel(undefined), null)
  assert.equal(selectionFromPanel(''), null)
  assert.equal(selectionFromPanel(3), 3)
  assert.equal(selectionFromPanel('4'), 4)
  assert.equal(selectionFromPanel('abc'), null)
})

test('feedRequest asks for the newest window or the whole pinned period', () => {
  assert.deepEqual(feedRequest(null), { round: null, limit: 60, commentLimit: 200 })
  assert.deepEqual(feedRequest(undefined), { round: null, limit: 60, commentLimit: 200 })
  assert.deepEqual(feedRequest(2), { round: 2, limit: 500, commentLimit: 1000 })
  assert.deepEqual(feedRequest('2'), { round: 2, limit: 500, commentLimit: 1000 })
})

test('postPeriodNote marks only older posts surfaced by this period\'s replies', () => {
  assert.equal(postPeriodNote({ post_id: 1, round: 0 }, 2, rounds), 'posted in #0')
  assert.equal(postPeriodNote({ post_id: 3, round: 1 }, 2, rounds, '发表于'), '发表于 2026-11')
  assert.equal(postPeriodNote({ post_id: 6, round: 2 }, 2, rounds), '')        // written this period
  assert.equal(postPeriodNote({ post_id: 6 }, 2, rounds), '')                  // legacy row without a round
  assert.equal(postPeriodNote({ post_id: 6, round: 0 }, null, rounds), '')     // no period pinned
  assert.equal(postPeriodNote(null, 2, rounds), '')
})
