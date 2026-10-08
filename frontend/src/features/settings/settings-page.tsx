import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Laptop, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { ErrorState, PageHeader } from '@/components/shared/common'
import { ThemeToggle } from '@/components/shared/theme-toggle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/hooks/use-auth'
import { authApi } from '@/services/api'
import { errorMessage } from '@/services/http'
import { keys, useAuditLogs, useSessions } from '@/services/queries'
import { formatDateTime, formatRelative } from '@/utils/format'
import { AUDIT_ACTION_LABEL } from '@/utils/status'

export const passwordSchema = z
  .object({
    current_password: z.string().min(1, 'Введите текущий пароль'),
    new_password: z
      .string()
      .min(12, 'Не короче 12 символов')
      .max(256, 'Слишком длинный пароль')
      .refine((v) => !/^\d+$/.test(v) && !/^[a-zа-яё]+$/i.test(v), 'Добавьте символы разных типов'),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'Пароли не совпадают' })
  .refine((v) => v.new_password !== v.current_password, { path: ['new_password'], message: 'Новый пароль должен отличаться от текущего' })
type PasswordValues = z.infer<typeof passwordSchema>

function PasswordCard() {
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<PasswordValues>({ resolver: zodResolver(passwordSchema), defaultValues: { current_password: '', new_password: '', confirm: '' } })
  const qc = useQueryClient()
  const change = useMutation({
    mutationFn: (v: PasswordValues) => authApi.changePassword(v.current_password, v.new_password),
    onSuccess: () => {
      toast.success('Пароль изменён. Другие сессии завершены.')
      reset()
      qc.invalidateQueries({ queryKey: keys.sessions })
    },
    onError: (e) => {
      const message = errorMessage(e)
      setError('root', { message })
      toast.error(message)
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Пароль</CardTitle>
        <CardDescription>После смены пароля все остальные устройства будут разлогинены.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit((v) => change.mutate(v))} noValidate className="max-w-md space-y-4">
          {([
            ['current_password', 'Текущий пароль', 'current-password'],
            ['new_password', 'Новый пароль', 'new-password'],
            ['confirm', 'Повторите новый пароль', 'new-password'],
          ] as const).map(([name, label, autocomplete]) => (
            <div key={name} className="space-y-2">
              <Label htmlFor={name}>{label}</Label>
              <Input id={name} type="password" autoComplete={autocomplete} aria-invalid={!!errors[name]} aria-describedby={errors[name] ? `${name}-error` : undefined} {...register(name)} />
              {errors[name] && <p id={`${name}-error`} className="text-sm text-destructive">{errors[name]?.message}</p>}
            </div>
          ))}
          {errors.root && <p role="alert" className="text-sm text-destructive">{errors.root.message}</p>}
          <Button type="submit" loading={change.isPending}>Сменить пароль</Button>
        </form>
      </CardContent>
    </Card>
  )
}

function SessionsCard() {
  const sessions = useSessions()
  const qc = useQueryClient()
  const revoke = useMutation({
    mutationFn: (id: string) => authApi.revokeSession(id),
    onSuccess: () => { toast.success('Сессия завершена'); qc.invalidateQueries({ queryKey: keys.sessions }) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Активные сессии</CardTitle>
        <CardDescription>Устройства, на которых выполнен вход</CardDescription>
      </CardHeader>
      <CardContent>
        {sessions.isLoading ? (
          <div role="status" aria-label="Загрузка сессий" className="space-y-2"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>
        ) : sessions.isError ? (
          <ErrorState message={errorMessage(sessions.error)} onRetry={() => sessions.refetch()} />
        ) : (
          <ul className="divide-y">
            {sessions.data?.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <Laptop className="size-5 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {(s.user_agent ?? 'Неизвестное устройство').slice(0, 60)} {s.current && <Badge variant="success" className="ml-1">Это устройство</Badge>}
                    </p>
                    <p className="text-xs text-muted-foreground">{s.ip_address ?? '—'} · активность {formatRelative(s.last_seen_at)}</p>
                  </div>
                </div>
                {!s.current && (
                  <Button variant="outline" size="sm" onClick={() => revoke.mutate(s.id)} loading={revoke.isPending && revoke.variables === s.id}>
                    Завершить
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function AuditCard() {
  const [offset, setOffset] = useState(0)
  const limit = 10
  const logs = useAuditLogs({ limit, offset })
  const total = logs.data?.total ?? 0
  return (
    <Card>
      <CardHeader>
        <CardTitle>Журнал действий</CardTitle>
        <CardDescription>Входы, подключения TikTok и публикации. Секреты в журнал не попадают.</CardDescription>
      </CardHeader>
      <CardContent>
        {logs.isLoading ? (
          <div role="status" aria-label="Загрузка журнала" className="space-y-2">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : logs.isError ? (
          <ErrorState message={errorMessage(logs.error)} onRetry={() => logs.refetch()} />
        ) : (
          <>
            <ul className="divide-y">
              {logs.data?.items.map((l) => (
                <li key={l.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                  <span className="min-w-0 truncate">{AUDIT_ACTION_LABEL[l.action] ?? l.action}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatDateTime(l.created_at)}</span>
                </li>
              ))}
              {logs.data?.items.length === 0 && <li className="py-6 text-center text-sm text-muted-foreground">Записей пока нет.</li>}
            </ul>
            <div className="mt-3 flex items-center justify-between text-sm text-muted-foreground">
              <span>{total === 0 ? 0 : offset + 1}–{Math.min(offset + limit, total)} из {total}</span>
              <div className="flex gap-1">
                <Button variant="outline" size="icon" aria-label="Предыдущая страница журнала" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}><ChevronLeft aria-hidden /></Button>
                <Button variant="outline" size="icon" aria-label="Следующая страница журнала" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}><ChevronRight aria-hidden /></Button>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function SettingsPage() {
  const { user } = useAuth()
  return (
    <>
      <PageHeader title="Настройки и безопасность" description="Профиль, оформление, пароль и активные сессии." />
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Профиль</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <dl className="space-y-3 text-sm">
              <div><dt className="text-muted-foreground">Адрес почты</dt><dd className="font-medium">{user?.email}</dd></div>
              <div><dt className="text-muted-foreground">Роль</dt><dd>{user?.role === 'admin' ? 'Администратор' : 'Участник'}</dd></div>
              <div><dt className="text-muted-foreground">Последний вход</dt><dd>{formatDateTime(user?.last_login_at)}</dd></div>
            </dl>
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Тема оформления</p>
              <ThemeToggle />
            </div>
          </CardContent>
        </Card>
        <PasswordCard />
        <SessionsCard />
        <AuditCard />
        <p className="flex items-start gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
          Сессии хранятся на сервере, cookie защищены (HttpOnly, Secure, SameSite). Токены TikTok зашифрованы и недоступны браузеру.
        </p>
      </div>
    </>
  )
}
