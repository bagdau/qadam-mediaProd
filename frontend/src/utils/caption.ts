export const CAPTION_LIMIT = 2200

export function captionUnits(value: string): number {
  return value.length
}

export function captionRemaining(value: string): number {
  return CAPTION_LIMIT - captionUnits(value)
}
