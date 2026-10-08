import { useEffect, useRef } from 'react'

export function useInterval(callback: () => void, delayMs: number | null): void {
  const callbackRef = useRef(callback)
  useEffect(() => {
    callbackRef.current = callback
  }, [callback])
  useEffect(() => {
    if (delayMs === null) return
    const timer = window.setInterval(() => callbackRef.current(), delayMs)
    return () => window.clearInterval(timer)
  }, [delayMs])
}
