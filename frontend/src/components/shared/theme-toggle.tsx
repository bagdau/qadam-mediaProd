import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme, type Theme } from '@/hooks/use-theme'
import { cn } from '@/utils/cn'

const OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Светлая', icon: Sun },
  { value: 'system', label: 'Системная', icon: Monitor },
  { value: 'dark', label: 'Тёмная', icon: Moon },
]

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme()
  return (
    <div role="radiogroup" aria-label="Тема оформления" className={cn('inline-flex rounded-lg border bg-card p-0.5', className)}>
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={theme === value}
          aria-label={label}
          title={label}
          onClick={() => setTheme(value)}
          className={cn(
            'inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground',
            theme === value && 'bg-accent text-accent-foreground',
          )}
        >
          <Icon className="size-4" aria-hidden />
        </button>
      ))}
    </div>
  )
}
