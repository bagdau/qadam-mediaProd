import { useOnlineStatus } from '@/hooks/use-online-status'

export function ConnectionHealth() {
  const online = useOnlineStatus()
  if (online) return null
  return <div role="status" className="bg-amber-100 p-2 text-center text-sm text-amber-950">Нет соединения. Изменения не отправляются.</div>
}
