import { captionRemaining } from '@/utils/caption'

export function CharacterCounter({ value }: { value: string }) {
  const remaining = captionRemaining(value)
  return <span aria-live="polite" className={remaining < 0 ? 'text-destructive' : 'text-muted-foreground'}>{remaining}</span>
}
