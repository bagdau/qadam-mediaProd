export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm">
      <p>{message}</p>
      {onRetry && <button className="mt-3 underline" onClick={onRetry}>Повторить</button>}
    </div>
  )
}
