import type { ReactNode } from 'react'

export function FormHint({ id, error, children }: { id: string; error?: boolean; children: ReactNode }) {
  return (
    <p id={id} role={error ? 'alert' : undefined} className={error ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'}>
      {children}
    </p>
  )
}
