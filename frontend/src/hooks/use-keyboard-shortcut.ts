import { useEffect } from 'react'

export function useKeyboardShortcut(key: string, action: () => void, enabled = true): void {
  useEffect(() => {
    if (!enabled) return
    const listener = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === key.toLowerCase()) {
        event.preventDefault()
        action()
      }
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [action, enabled, key])
}
