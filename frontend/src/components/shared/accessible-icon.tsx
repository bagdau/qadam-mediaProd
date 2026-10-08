import type { ReactNode } from 'react'

export function AccessibleIcon({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span role="img" aria-label={label} className="inline-flex">
      {children}
    </span>
  )
}
