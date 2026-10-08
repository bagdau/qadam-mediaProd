import { AlertTriangle, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { AccountStatus, PublicationStatus } from '@/types/api'
import { cn } from '@/utils/cn'
import { ACCOUNT_STATUS, PUBLICATION_STATUS } from '@/utils/status'

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center', className)}>
      <div className="flex size-12 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Icon className="size-6" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-xl border border-destructive/30 bg-danger-soft p-5 sm:flex-row sm:items-center">
      <AlertTriangle className="size-5 shrink-0 text-destructive" aria-hidden />
      <p className="flex-1 text-sm">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  )
}

export function Notice({ tone = 'info', title, children }: { tone?: 'info' | 'warning' | 'success'; title?: string; children: ReactNode }) {
  const styles = {
    info: 'border-info/30 bg-info-soft',
    warning: 'border-warning/40 bg-warning-soft',
    success: 'border-success/30 bg-success-soft',
  }[tone]
  return (
    <div role="note" className={cn('rounded-lg border p-4 text-sm', styles)}>
      {title && <p className="mb-1 font-medium">{title}</p>}
      <div className="text-foreground/90">{children}</div>
    </div>
  )
}

export function PublicationStatusBadge({ status }: { status: PublicationStatus }) {
  const meta = PUBLICATION_STATUS[status]
  return (
    <Badge variant={meta.variant} title={meta.description}>
      {meta.label}
    </Badge>
  )
}

export function AccountStatusBadge({ status }: { status: AccountStatus }) {
  const meta = ACCOUNT_STATUS[status]
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}
