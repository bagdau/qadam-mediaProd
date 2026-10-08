import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'
import { cn } from '@/utils/cn'

const badgeVariants = cva('inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap', {
  variants: {
    variant: {
      default: 'border-transparent bg-primary text-primary-foreground',
      secondary: 'border-transparent bg-secondary text-secondary-foreground',
      outline: 'text-foreground',
      success: 'border-transparent bg-success-soft text-success',
      warning: 'border-transparent bg-warning-soft text-warning',
      info: 'border-transparent bg-info-soft text-info',
      destructive: 'border-transparent bg-danger-soft text-destructive',
    },
  },
  defaultVariants: { variant: 'default' },
})

function Badge({ className, variant, ...props }: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
