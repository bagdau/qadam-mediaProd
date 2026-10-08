import * as React from 'react'
import { cn } from '@/utils/cn'

function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div aria-hidden className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}

export { Skeleton }
