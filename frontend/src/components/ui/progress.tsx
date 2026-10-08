import * as ProgressPrimitive from '@radix-ui/react-progress'
import * as React from 'react'
import { cn } from '@/utils/cn'

function Progress({ className, value, ...props }: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  return (
    <ProgressPrimitive.Root className={cn('relative h-2 w-full overflow-hidden rounded-full bg-secondary', className)} value={value} {...props}>
      <ProgressPrimitive.Indicator className="h-full bg-primary transition-all" style={{ width: `${value ?? 0}%` }} />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
