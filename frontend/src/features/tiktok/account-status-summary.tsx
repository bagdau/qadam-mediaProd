import type { AccountStatus } from '@/types/api'

const messages: Record<AccountStatus, string> = {
  active: 'Аккаунт готов к публикации',
  needs_reauth: 'Подключите аккаунт заново',
  revoked: 'Доступ к аккаунту отключён',
}

export function AccountStatusSummary({ status }: { status: AccountStatus }) {
  return <p role="status">{messages[status]}</p>
}
