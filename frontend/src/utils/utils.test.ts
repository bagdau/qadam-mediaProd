import { describe, expect, it } from 'vitest'
import { lastSevenDays } from '@/features/dashboard/dashboard-page'
import { safeNext } from '@/features/auth/login-page'
import { stepIndex } from '@/features/publishing/publication-detail-page'
import { formatBytes, formatDuration, formatRelative, newIdempotencyKey } from '@/utils/format'
import { isActiveStatus, PUBLICATION_STATUS } from '@/utils/status'

describe('formatting', () => {
  it('formats byte sizes', () => {
    expect(formatBytes(0)).toBe('0 Б')
    expect(formatBytes(1536)).toBe('1.5 КБ')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 МБ')
    expect(formatBytes(-1)).toBe('—')
  })
  it('formats durations', () => {
    expect(formatDuration(65)).toBe('1:05')
    expect(formatDuration(null)).toBe('—')
  })
  it('formats relative time', () => {
    const now = Date.parse('2026-10-09T12:00:00Z')
    expect(formatRelative('2026-10-09T11:59:50Z', now)).toBe('только что')
    expect(formatRelative('2026-10-09T11:00:00Z', now)).toMatch(/час/)
    expect(formatRelative(null)).toBe('—')
  })
  it('generates distinct idempotency keys', () => {
    const keys = new Set(Array.from({ length: 50 }, newIdempotencyKey))
    expect(keys.size).toBe(50)
    expect([...keys][0].length).toBeGreaterThanOrEqual(8)
  })
})

describe('safeNext (open-redirect guard)', () => {
  it.each([
    ['/accounts', '/accounts'],
    ['/publications/abc?x=1', '/publications/abc?x=1'],
    [null, '/'],
    ['', '/'],
    ['https://evil.example', '/'],
    ['//evil.example', '/'],
    ['/\\evil.example', '/'],
    ['javascript:alert(1)', '/'],
  ])('%s -> %s', (input, expected) => {
    expect(safeNext(input)).toBe(expected)
  })
})

describe('dashboard helpers', () => {
  it('fills the last seven days oldest-first', () => {
    const days = lastSevenDays([{ date: '2026-10-08', total: 3, published: 2 }], new Date('2026-10-09T10:00:00Z'))
    expect(days).toHaveLength(7)
    expect(days[0].date).toBe('2026-10-03')
    expect(days[6]).toEqual({ date: '2026-10-09', total: 0, published: 0 })
    expect(days[5]).toEqual({ date: '2026-10-08', total: 3, published: 2 })
  })
})

describe('status model', () => {
  it('has a label for every status and knows which are active', () => {
    for (const status of Object.keys(PUBLICATION_STATUS) as (keyof typeof PUBLICATION_STATUS)[]) {
      expect(PUBLICATION_STATUS[status].label).toBeTruthy()
    }
    expect(['QUEUED', 'INITIATING', 'UPLOADING', 'PROCESSING'].every((s) => isActiveStatus(s as never))).toBe(true)
    expect(['PUBLISHED', 'FAILED', 'NEEDS_REVIEW', 'CANCELLED', 'INBOX_DELIVERED'].some((s) => isActiveStatus(s as never))).toBe(false)
  })
  it('maps statuses to stepper positions', () => {
    expect(stepIndex('QUEUED')).toBe(0)
    expect(stepIndex('INITIATING')).toBe(1)
    expect(stepIndex('UPLOADING')).toBe(1)
    expect(stepIndex('PROCESSING')).toBe(2)
    expect(stepIndex('PUBLISHED')).toBe(3)
    expect(stepIndex('INBOX_DELIVERED')).toBe(3)
  })
})
