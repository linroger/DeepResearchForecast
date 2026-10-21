import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createLatestRequestGate,
  downloadFilenameFromDisposition,
  hasPdfMagic,
  normalizeReportTranslations,
  normalizeVerbatimChunks,
  reportLanguageOptions,
  reportTranslationAction,
  reportTranslationIssues,
  reportTranslationPartial,
  reportTranslationPartialNote,
  reportTranslationPollOutcome,
  reportTranslationUpdateAction,
  reportTranslationUpdateLabel,
  reportTranslationUpdateTitle,
  verbatimChunkSummary,
} from '../src/utils/reportLanguages.js'

const SOURCE_SHA = 'a'.repeat(64)
const TARGET_SHA = 'b'.repeat(64)

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function verifiedMeta() {
  const row = {
    report_id: 'report_123',
    lang: 'zh',
    source_lang: 'en',
    source_markdown_sha256: SOURCE_SHA,
    markdown_sha256: TARGET_SHA,
    path: 'full_report.zh.md',
    citations_path: 'citations.zh.json',
    final_audit_path: 'final_audit.zh.json',
    available: true,
  }
  return {
    report_id: 'report_123',
    translations: [row, { ...row }],
    translation_status: {
      report_id: 'report_123',
      source_lang: 'en',
      target_lang: 'zh',
      requested_lang: 'zh',
      status: 'available',
      available: true,
      can_generate: false,
      markdown_sha256: TARGET_SHA,
      issues: [],
      translation: {
        lang: 'zh',
        source_lang: 'en',
        path: 'full_report.zh.md',
        markdown_sha256: TARGET_SHA,
        available: true,
      },
    },
  }
}

test('language options expose only the current backend-verified publication row', () => {
  const meta = verifiedMeta()

  assert.deepEqual(normalizeReportTranslations(meta).map(row => row.lang), ['zh'])
  assert.deepEqual(
    reportLanguageOptions(meta, code => ({ en: 'EN', zh: '中文' }[code] || 'Original')),
    [
      { key: null, code: 'en', label: 'EN' },
      { key: 'zh', code: 'zh', label: '中文' },
    ],
  )
})

test('missing availability and stale or unaudited translation rows never become toggles', () => {
  const cases = [
    ['missing explicit available', meta => { delete meta.translations[0].available; delete meta.translations[1].available }],
    ['wrong report identity', meta => { meta.translations.forEach(row => { row.report_id = 'report_old' }) }],
    ['missing source fingerprint', meta => { meta.translations.forEach(row => { delete row.source_markdown_sha256 }) }],
    ['missing target fingerprint', meta => { meta.translations.forEach(row => { delete row.markdown_sha256 }) }],
    ['missing citation identity', meta => { meta.translations.forEach(row => { delete row.citations_path }) }],
    ['missing final audit identity', meta => { meta.translations.forEach(row => { delete row.final_audit_path }) }],
    ['stale backend status', meta => {
      meta.translation_status.status = 'stale'
      meta.translation_status.available = false
    }],
    ['missing backend verification marker', meta => { delete meta.translation_status.translation }],
    ['verification fingerprint mismatch', meta => {
      meta.translation_status.translation.markdown_sha256 = 'c'.repeat(64)
    }],
  ]

  for (const [name, mutate] of cases) {
    const meta = clone(verifiedMeta())
    mutate(meta)
    assert.deepEqual(normalizeReportTranslations(meta), [], name)
    assert.deepEqual(reportLanguageOptions(meta), [], name)
  }
})

test('translation action is exposed strictly according to can_generate', () => {
  const failed = reportTranslationAction({
    report_id: 'report_123',
    translation_status: {
      report_id: 'report_123',
      source_lang: 'en',
      target_lang: 'zh',
      status: 'failed',
      available: false,
      can_generate: true,
      issues: ['numeric parity'],
    },
  })

  assert.deepEqual(failed, {
    targetLang: 'zh',
    status: 'failed',
    issues: ['numeric parity'],
    retry: true,
  })
  assert.equal(reportTranslationAction(verifiedMeta()), null)
  assert.equal(reportTranslationAction({
    report_id: 'report_123',
    translation_status: {
      report_id: 'report_123',
      target_lang: 'zh', available: false, can_generate: false,
    },
  }), null)
  assert.equal(reportTranslationAction({
    report_id: 'report_123',
    translation_status: {
      report_id: 'report_123',
      target_lang: 'zh', available: false, can_generate: 'true',
    },
  }), null)
  assert.equal(reportTranslationAction({
    report_id: 'report_123',
    translation_status: {
      report_id: 'report_old',
      target_lang: 'zh', available: false, can_generate: true,
    },
  }), null)

  const stale = clone(verifiedMeta())
  stale.translation_status.status = 'stale'
  stale.translation_status.available = false
  stale.translation_status.can_generate = true
  stale.translation_status.issues = ['translation audit belongs to older report bytes']
  assert.equal(reportTranslationAction(stale)?.retry, true)

  const missing = reportTranslationAction({
    report_id: 'report_123',
    translation_status: {
      report_id: 'report_123',
      target_lang: 'zh',
      status: 'missing',
      available: false,
      can_generate: true,
    },
  })
  assert.equal(missing?.retry, false)
})

test('translation polling recognizes every terminal state and equivalent', () => {
  const failures = [
    'failed', 'interrupted', 'invalid', 'stale', 'unavailable',
    'blocked', 'disabled', 'unsupported', 'not_found', 'source_language',
    'cancelled', 'canceled', 'aborted', 'expired', 'error',
  ]
  for (const status of failures) {
    const outcome = reportTranslationPollOutcome({
      status,
      available: false,
      can_generate: true,
      issues: [`${status} issue`],
    }, 'task_1')
    assert.equal(outcome.terminal, true, status)
    assert.equal(outcome.available, false, status)
    assert.equal(outcome.canGenerate, true, status)
    assert.deepEqual(outcome.issues, [`${status} issue`], status)
  }

  const available = reportTranslationPollOutcome({
    status: 'available', available: true, can_generate: false,
  }, 'task_1')
  assert.equal(available.terminal, true)
  assert.equal(available.available, true)

  const completed = reportTranslationPollOutcome({
    status: 'completed',
    available: false,
    can_generate: false,
    result: { available: true },
  }, 'task_1')
  assert.equal(completed.terminal, true)
  assert.equal(completed.available, true)

  const completedWithoutArtifact = reportTranslationPollOutcome({
    status: 'completed', available: false, can_generate: true,
  }, 'task_1')
  assert.equal(completedWithoutArtifact.terminal, true)
  assert.equal(completedWithoutArtifact.available, false)
  assert.equal(completedWithoutArtifact.reason, 'terminal_without_artifact')
})

test('translation polling continues only for a recognized active state bound to the task', () => {
  for (const status of ['pending', 'processing', 'generating', 'queued', 'running', 'in_progress']) {
    const outcome = reportTranslationPollOutcome({
      status,
      task_id: 'task_1',
      available: false,
      can_generate: false,
    }, 'task_1')
    assert.equal(outcome.terminal, false, status)
    assert.equal(outcome.available, false, status)
  }

  const restartedBackend = reportTranslationPollOutcome({
    status: 'generating',
    available: false,
    can_generate: false,
  }, 'task_1')
  assert.equal(restartedBackend.terminal, true)
  assert.equal(restartedBackend.status, 'interrupted')
  assert.equal(restartedBackend.reason, 'task_missing')

  const wrongTask = reportTranslationPollOutcome({
    status: 'processing',
    task_id: 'task_2',
    available: false,
    can_generate: true,
  }, 'task_1')
  assert.equal(wrongTask.terminal, true)
  assert.equal(wrongTask.status, 'invalid')
  assert.equal(wrongTask.reason, 'task_mismatch')

  const unknown = reportTranslationPollOutcome({
    status: 'mystery', available: false, can_generate: true,
  }, 'task_1')
  assert.equal(unknown.terminal, true)
  assert.equal(unknown.status, 'invalid')
  assert.equal(unknown.reason, 'unknown_status')
})

test('translation issues are durable, normalized, and deduplicated', () => {
  assert.deepEqual(reportTranslationIssues({
    error: 'worker stopped',
    issues: ['numeric parity', 'numeric parity', null],
    result: { issues: ['missing references'] },
  }), ['worker stopped', 'numeric parity', 'missing references'])
})

test('latest request gate aborts and rejects stale export cleanup', () => {
  const gate = createLatestRequestGate()
  const first = gate.begin()
  assert.equal(gate.isCurrent(first), true)

  const second = gate.begin()
  assert.equal(first.signal.aborted, true)
  assert.equal(gate.isCurrent(first), false)
  assert.equal(gate.finish(first), false)
  assert.equal(gate.isCurrent(second), true)
  assert.equal(gate.finish(second), true)
  assert.equal(gate.isCurrent(second), false)

  const third = gate.begin()
  gate.cancel()
  assert.equal(third.signal.aborted, true)
  assert.equal(gate.isCurrent(third), false)
  assert.equal(gate.finish(third), false)
})

test('download validation preserves server filenames and rejects non-PDF bytes', () => {
  assert.equal(
    downloadFilenameFromDisposition(
      "attachment; filename*=UTF-8''report_123.zh.pdf",
      'fallback.pdf',
    ),
    'report_123.zh.pdf',
  )
  assert.equal(
    downloadFilenameFromDisposition('attachment; filename="../bad.pdf"', 'fallback.pdf'),
    '.._bad.pdf',
  )
  assert.equal(downloadFilenameFromDisposition('', 'fallback.pdf'), 'fallback.pdf')
  assert.equal(hasPdfMagic(new TextEncoder().encode('%PDF-1.7')), true)
  assert.equal(hasPdfMagic(new TextEncoder().encode('<html>error</html>')), false)
})

// ---------- FILTER-SAFE: partial translations (disclosed source-language passages) ----------
const EN = (zh, en) => en
const ZH = zh => zh

function verbatimChunk(overrides = {}) {
  return {
    chunk: 1, heading: 'Executive Summary', reason: 'content_filter', scope: 'unit',
    detail: 'HTTP 400 code 1301', lines: 1, chars: 96,
    sample: 'The leadership of both governments signalled a readiness to extend the truce.',
    kept_lines: 1,
    ...overrides,
  }
}

// The backend payload for a published partial translation: the verified row (which GET
// /api/report/<id> copies into translations[]) carries the chunks, translation_status
// carries partial / outdated / can_update.
function partialMeta({ chunks = [verbatimChunk()], outdated = false, canUpdate = true, residual } = {}) {
  const meta = verifiedMeta()
  const partial = chunks.length > 0
  const residualLines = residual != null ? residual : chunks.reduce((sum, c) => sum + (c.kept_lines || 0), 0)
  for (const row of [...meta.translations, meta.translation_status.translation]) {
    row.residual_source_lines = residualLines
    row.translator_version = outdated ? '2026-09-29.1' : '2026-10-17.1'
    row.partial = partial
    row.verbatim_chunks = chunks
  }
  Object.assign(meta.translation_status, {
    can_generate: canUpdate, partial, outdated, can_update: canUpdate && (partial || outdated),
  })
  return meta
}

test('verbatim chunks are normalized defensively and capped', () => {
  const chunks = normalizeVerbatimChunks([
    verbatimChunk(),
    verbatimChunk({ chunk: '4', heading: '  Scenario   Analysis ', reason: 'INTEGRITY', scope: 'Section', lines: '3', kept_lines: 2, detail: null, sample: 'x'.repeat(300) }),
    verbatimChunk({ chunk: -1, reason: '', scope: 'paragraph', lines: -2, chars: 'n/a', kept_lines: undefined, sample: '' }),
    'not a chunk', null, 7, ['chunk'],
  ])
  assert.equal(chunks.length, 3)
  assert.deepEqual(chunks[0], {
    chunk: 1, heading: 'Executive Summary', reason: 'content_filter', scope: 'unit',
    detail: 'HTTP 400 code 1301', lines: 1, chars: 96,
    sample: 'The leadership of both governments signalled a readiness to extend the truce.',
    keptLines: 1,
  })
  assert.equal(chunks[1].chunk, 4)
  assert.equal(chunks[1].heading, 'Scenario Analysis')
  assert.equal(chunks[1].reason, 'integrity')
  assert.equal(chunks[1].scope, 'section')
  assert.equal(chunks[1].lines, 3)
  assert.equal(chunks[1].keptLines, 2)
  assert.equal(chunks[1].detail, '')
  assert.equal(chunks[1].sample.length, 120)
  assert.ok(chunks[1].sample.endsWith('…'))
  assert.deepEqual(
    [chunks[2].chunk, chunks[2].reason, chunks[2].scope, chunks[2].lines, chunks[2].chars, chunks[2].keptLines, chunks[2].sample],
    [null, 'unknown', '', 0, 0, 0, ''],
  )
  assert.deepEqual(normalizeVerbatimChunks(null), [])
  assert.deepEqual(normalizeVerbatimChunks({ chunk: 1 }), [])
  assert.equal(normalizeVerbatimChunks(Array.from({ length: 60 }, () => verbatimChunk())).length, 48)
})

test('a partial translation row yields the note, its kept passages and the retry action', () => {
  const chunks = [
    verbatimChunk(),
    verbatimChunk({ chunk: 4, heading: 'Scenario Analysis', reason: 'integrity', scope: 'section', lines: 3, kept_lines: 3, sample: 'Each scenario assumes the truce holds.' }),
  ]
  const meta = partialMeta({ chunks })

  const partial = reportTranslationPartial(meta, 'zh')
  assert.equal(partial.targetLang, 'zh')
  assert.equal(partial.sourceLang, 'en')
  assert.equal(partial.chunkCount, 2)
  assert.equal(partial.residualLines, 4)
  assert.deepEqual(partial.reasons, ['content_filter', 'integrity'])
  assert.equal(partial.canUpdate, true)
  assert.deepEqual(partial.chunks.map(c => [c.chunk, c.heading, c.reason, c.scope, c.keptLines]), [
    [1, 'Executive Summary', 'content_filter', 'unit', 1],
    [4, 'Scenario Analysis', 'integrity', 'section', 3],
  ])
  // Default language = the report's translation target; the source language is never partial.
  assert.deepEqual(reportTranslationPartial(meta), partial)
  assert.equal(reportTranslationPartial(meta, 'en'), null)

  assert.equal(
    reportTranslationPartialNote(partial, EN),
    'Partial translation: 2 passages kept in the source language (4 lines)',
  )
  assert.equal(reportTranslationPartialNote(partial, ZH), '译文不完整：2 处段落保留原文（共 4 行）')
  assert.equal(verbatimChunkSummary(partial.chunks[0], EN), 'paragraph · provider content filter · 1 line')
  assert.equal(verbatimChunkSummary(partial.chunks[0], ZH), '段落 · 提供方内容过滤 · 1 行')
  assert.equal(verbatimChunkSummary(partial.chunks[1], EN), 'whole section · integrity audit · 3 lines')
  assert.equal(verbatimChunkSummary(partial.chunks[1], ZH), '整节 · 完整性审计 · 3 行')

  const action = reportTranslationUpdateAction(meta)
  assert.deepEqual(action, { targetLang: 'zh', outdated: false, partial: true, reason: 'partial' })
  assert.equal(reportTranslationUpdateLabel(action, EN), 'Retry translation')
  assert.equal(reportTranslationUpdateLabel(action, ZH), '重试翻译')
  assert.equal(reportTranslationUpdateLabel(action, EN, true), 'Retrying translation…')
  assert.equal(reportTranslationUpdateLabel(action, ZH, true), '正在重试翻译…')
  assert.match(reportTranslationUpdateTitle(action, EN), /^This translation is partial: some passages were kept in the source language/)
  assert.match(reportTranslationUpdateTitle(action, ZH), /^此译文不完整：部分段落保留原文/)
})

test('a complete translation is unchanged: no partial note, update action only when outdated', () => {
  const complete = partialMeta({ chunks: [], residual: 1 })
  assert.equal(reportTranslationPartial(complete, 'zh'), null)
  assert.equal(reportTranslationUpdateAction(complete), null)
  assert.equal(reportTranslationPartialNote(null, EN), '')
  assert.equal(reportTranslationUpdateLabel(null, EN), '')
  assert.equal(reportTranslationUpdateTitle(null, EN), '')

  const outdated = partialMeta({ chunks: [], outdated: true })
  assert.equal(reportTranslationPartial(outdated, 'zh'), null)
  const action = reportTranslationUpdateAction(outdated)
  assert.deepEqual(action, { targetLang: 'zh', outdated: true, partial: false, reason: 'outdated' })
  assert.equal(reportTranslationUpdateLabel(action, EN), 'Update translation')
  assert.equal(reportTranslationUpdateLabel(action, EN, true), 'Updating translation…')
  assert.equal(reportTranslationUpdateLabel(action, ZH), '更新翻译')
  assert.equal(
    reportTranslationUpdateTitle(action, EN),
    'This translation was made by an older translation engine (for example, months in dates may be missing); regenerate it',
  )

  // Both reasons: the stronger "update" wording wins, the tooltip names both.
  const both = partialMeta({ outdated: true })
  const bothAction = reportTranslationUpdateAction(both)
  assert.deepEqual(bothAction, { targetLang: 'zh', outdated: true, partial: true, reason: 'outdated' })
  assert.equal(reportTranslationUpdateLabel(bothAction, EN), 'Update translation')
  assert.match(reportTranslationUpdateTitle(bothAction, EN), /older translation engine .*; This translation is partial/)
  assert.match(reportTranslationUpdateTitle(bothAction, ZH), /旧版翻译引擎.*；此译文不完整/)
})

test('the retry action follows the backend can_update flag and the identity contract', () => {
  // can_update false (bilingual disabled / report not publishable) → no retry even when partial.
  const locked = partialMeta({ canUpdate: false })
  assert.equal(reportTranslationUpdateAction(locked), null)
  assert.equal(reportTranslationPartial(locked, 'zh')?.canUpdate, false)

  // Strict booleans only.
  const loose = partialMeta()
  loose.translation_status.can_update = 'true'
  assert.equal(reportTranslationUpdateAction(loose), null)
  const notAvailable = partialMeta()
  notAvailable.translation_status.available = false
  assert.equal(reportTranslationUpdateAction(notAvailable), null)
  const unsupported = partialMeta()
  unsupported.translation_status.target_lang = 'fr'
  assert.equal(reportTranslationUpdateAction(unsupported), null)

  // The top-level flag alone is enough for the action; the note still needs a verified row.
  const flagOnly = clone(verifiedMeta())
  Object.assign(flagOnly.translation_status, { partial: true, outdated: false, can_update: true })
  assert.deepEqual(reportTranslationUpdateAction(flagOnly), { targetLang: 'zh', outdated: false, partial: true, reason: 'partial' })
  const flagOnlyPartial = reportTranslationPartial(flagOnly, 'zh')
  assert.equal(flagOnlyPartial.chunkCount, 0)
  assert.equal(reportTranslationPartialNote(flagOnlyPartial, EN), 'Partial translation: some passages were kept in the source language')

  // Chunks on the row imply a partial translation even if the flag is missing.
  const chunksOnly = clone(verifiedMeta())
  chunksOnly.translations.forEach(row => { row.verbatim_chunks = [verbatimChunk()] })
  assert.equal(reportTranslationPartial(chunksOnly, 'zh')?.chunkCount, 1)

  // A translation that fails the identity contract has no toggle and therefore no note.
  const stale = partialMeta()
  stale.translation_status.status = 'stale'
  stale.translation_status.available = false
  assert.equal(reportTranslationPartial(stale, 'zh'), null)
  assert.equal(reportTranslationUpdateAction(stale), null)
})
