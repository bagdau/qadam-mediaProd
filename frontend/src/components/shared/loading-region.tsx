export function LoadingRegion({ label = 'Загрузка' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="animate-pulse rounded-lg border p-4">
      <span className="sr-only">{label}</span>
      <div className="h-4 w-2/3 rounded bg-muted" />
    </div>
  )
}
