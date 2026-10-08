import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link2, LogOut, RefreshCw, ShieldCheck, Users } from 'lucide-react'
import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { AccountStatusBadge, EmptyState, ErrorState, Notice, PageHeader } from '@/components/shared/common'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { accountsApi } from '@/services/api'
import { errorMessage } from '@/services/http'
import { keys, useAccounts, useMeta } from '@/services/queries'
import type { Account } from '@/types/api'
import { formatDateTime, formatRelative } from '@/utils/format'

export const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  oauth_state_invalid: 'Ссылка подключения устарела или уже использована. Начните подключение заново.',
  oauth_state_missing: 'TikTok не передал параметр проверки. Начните подключение заново.',
  oauth_denied: 'Вы не разрешили доступ в TikTok. Подключение отменено.',
  oauth_exchange_failed: 'TikTok отклонил код авторизации. Попробуйте подключить аккаунт ещё раз.',
  oauth_code_missing: 'TikTok не вернул код авторизации. Попробуйте ещё раз.',
  upstream_unavailable: 'TikTok временно недоступен. Повторите подключение через минуту.',
}

const SCOPE_LABEL: Record<string, string> = {
  'user.info.basic': 'Профиль',
  'video.publish': 'Прямая публикация',
  'video.upload': 'Загрузка в черновики',
}

function AccountCard({ account }: { account: Account }) {
  const qc = useQueryClient()
  const refresh = useMutation({
    mutationFn: () => accountsApi.refresh(account.id),
    onSuccess: () => {
      toast.success('Доступ обновлён')
      qc.invalidateQueries({ queryKey: keys.accounts })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const disconnect = useMutation({
    mutationFn: () => accountsApi.disconnect(account.id),
    onSuccess: () => {
      toast.success('Аккаунт отключён, токены удалены')
      qc.invalidateQueries({ queryKey: keys.accounts })
      qc.invalidateQueries({ queryKey: keys.dashboard })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const inactive = account.status !== 'active'
  const name = account.display_name || account.username || 'TikTok-аккаунт'

  return (
    <Card>
      <CardContent className="space-y-4 p-5 sm:p-5">
        <div className="flex items-start gap-4">
          {account.avatar_url ? (
            <img src={account.avatar_url} alt="" className="size-12 shrink-0 rounded-full bg-muted object-cover" referrerPolicy="no-referrer" />
          ) : (
            <div className="flex size-12 shrink-0 items-center justify-center rounded-full bg-accent text-lg font-semibold text-accent-foreground" aria-hidden>
              {name.charAt(0).toUpperCase()}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate font-semibold">{name}</h3>
              <AccountStatusBadge status={account.status} />
            </div>
            <p className="mt-1 text-sm text-muted-foreground">Подключён {formatRelative(account.connected_at)}</p>
          </div>
        </div>

        {account.scopes.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Выданные разрешения">
            {account.scopes.map((s) => (
              <li key={s} className="rounded-md bg-secondary px-2 py-1 text-xs text-secondary-foreground" title={s}>
                {SCOPE_LABEL[s] ?? s}
              </li>
            ))}
          </ul>
        )}

        {account.status === 'active' && (
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground">Токен доступа до</dt>
              <dd>{formatDateTime(account.access_expires_at)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Обновление до</dt>
              <dd>{formatDateTime(account.refresh_expires_at)}</dd>
            </div>
          </dl>
        )}
        {inactive && account.status === 'needs_reauth' && (
          <Notice tone="warning">Доступ недействителен (пользователь отозвал его или срок истёк). Подключите аккаунт заново.</Notice>
        )}

        <div className="flex flex-wrap gap-2">
          {account.status === 'active' && (
            <Button variant="outline" size="sm" onClick={() => refresh.mutate()} loading={refresh.isPending}>
              <RefreshCw aria-hidden /> Обновить доступ
            </Button>
          )}
          {account.status !== 'revoked' && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive">
                  <LogOut aria-hidden /> Отключить
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Отключить {name}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Мы отзовём доступ в TikTok и удалим сохранённые токены. Уже опубликованные видео останутся в TikTok. Публиковать в этот аккаунт
                    можно будет только после повторного подключения.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Отмена</AlertDialogCancel>
                  <AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={() => disconnect.mutate()}>
                    Отключить аккаунт
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function AccountsPage() {
  const [params, setParams] = useSearchParams()
  const accounts = useAccounts()
  const meta = useMeta()
  const qc = useQueryClient()

  const connect = useMutation({
    mutationFn: accountsApi.startOAuth,
    onSuccess: (url) => {
      window.location.assign(url) // leave for TikTok's official consent page
    },
    onError: (e) => toast.error(errorMessage(e, 'Не удалось начать подключение')),
  })

  // Result of the OAuth round-trip arrives as query parameters; show it once, then clean the URL.
  useEffect(() => {
    const connected = params.get('connected')
    const oauthError = params.get('oauth_error')
    if (!connected && !oauthError) return
    if (connected) {
      toast.success('TikTok-аккаунт подключён')
      qc.invalidateQueries({ queryKey: keys.accounts })
    } else if (oauthError) {
      toast.error(OAUTH_ERROR_MESSAGES[oauthError] ?? 'Не удалось подключить TikTok')
    }
    setParams({}, { replace: true })
  }, [params, setParams, qc])

  const notConfigured = meta.data && !meta.data.tiktok_configured
  const visible = accounts.data ?? []

  return (
    <>
      <PageHeader
        title="Аккаунты TikTok"
        description="Подключайте аккаунты через официальный вход TikTok. Пароль TikTok нам не передаётся."
        actions={
          <Button onClick={() => connect.mutate()} loading={connect.isPending} disabled={notConfigured}>
            <Link2 aria-hidden /> Подключить TikTok
          </Button>
        }
      />
      <div className="space-y-4">
        {notConfigured && (
          <Notice tone="warning" title="Интеграция TikTok не настроена">
            На сервере не заданы TIKTOK_CLIENT_KEY и TIKTOK_CLIENT_SECRET. Подключение аккаунтов недоступно, пока администратор их не добавит.
          </Notice>
        )}
        {meta.data && meta.data.tiktok_configured && !meta.data.tiktok_client_audited && (
          <Notice tone="info" title="Режим неаудированного приложения">
            TikTok разрешает такому приложению публиковать только с видимостью «Только я», в закрытые аккаунты, и ограничивает число
            пользователей за 24 часа.
          </Notice>
        )}

        {accounts.isLoading ? (
          <div role="status" aria-label="Загрузка аккаунтов" className="grid gap-4 md:grid-cols-2">
            <Skeleton className="h-52" />
            <Skeleton className="h-52" />
          </div>
        ) : accounts.isError ? (
          <ErrorState message={errorMessage(accounts.error, 'Не удалось загрузить аккаунты')} onRetry={() => accounts.refetch()} />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={Users}
            title="Аккаунтов пока нет"
            description="Нажмите «Подключить TikTok», разрешите доступ на странице TikTok — и вернётесь сюда уже с подключённым аккаунтом."
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">{visible.map((a) => <AccountCard key={a.id} account={a} />)}</div>
        )}

        <p className="flex items-start gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
          Токены хранятся на сервере в зашифрованном виде и никогда не передаются в браузер.
        </p>
      </div>
    </>
  )
}
