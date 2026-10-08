export type DateRange = { from: Date; to: Date }

export function lastDays(days: number, now = new Date()): DateRange {
  if (!Number.isInteger(days) || days < 1) throw new Error('days must be a positive integer')
  const to = new Date(now)
  const from = new Date(now)
  from.setDate(from.getDate() - days)
  return { from, to }
}
