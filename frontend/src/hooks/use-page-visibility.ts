import { useEffect, useState } from 'react'

export function usePageVisibility(): DocumentVisibilityState {
  const [visibility, setVisibility] = useState(document.visibilityState)
  useEffect(() => {
    const update = () => setVisibility(document.visibilityState)
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  return visibility
}
