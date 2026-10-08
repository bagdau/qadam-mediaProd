export function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, Math.round(value)))
}

export function progressLabel(value: number): string {
  return `${clampPercent(value)}%`
}
