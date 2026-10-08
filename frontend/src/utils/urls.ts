export function safeInternalPath(value: string | null | undefined, fallback = '/'): string {
  if (!value?.startsWith('/') || value.startsWith('//') || value.includes('\\')) return fallback
  return value
}

export function withQuery(path: string, values: Record<string, string | undefined>): string {
  const params = new URLSearchParams(Object.entries(values).filter((entry): entry is [string, string] => entry[1] !== undefined))
  const query = params.toString()
  return query ? `${path}?${query}` : path
}
