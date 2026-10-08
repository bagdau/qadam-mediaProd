import { CheckCircle2, Clock, History, Send, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState, Notice, PageHeader, PublicationStatusBadge } from '@/components/shared/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/services/http'
import { useDashboard, useMeta } from '@/services/queries'
import type { Dashboard } from '@/types/api'
import { formatRelative } from '@/utils/format'
import { PRIVACY_LABEL } from '@/utils/status'

function Stat({ label, value, icon, hint }: { label: string; value: number; icon: ReactNode; hint?: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-5 sm:p-5">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">{icon}</div>
        <div className="min-w-0">
          <p className="text-2xl leading-none font-semibold tabular-nums">{value}</p>
          <p className="mt-1 truncate text-sm text-muted-foreground">{label}</p>
          {hint && <p className="truncate text-xs text-muted-foreground">{hint}</p>}
        </div>
      </CardContent>
    </Card>
  )
}

/** Seven most recent days, oldest first, filling days without activity with zeros. */
export function lastSevenDays(daily: Dashboard['daily'], today: Date = new Date()): { date: string; total: number; published: number }[] {
  const byDate = new Map(daily.map((d) => [d.date, d]))
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - (6 - i)))
    const key = d.toISOString().slice(0, 10)
    return byDate.get(key) ?? { date: key, total: 0, published: 0 }
  })
}

function ActivityChart({ daily }: { daily: Dashboard['daily'] }) {
  const days = lastSevenDays(daily)
  const max = Math.max(1, ...days.map((d) => d.total))
  const summary = days.map((d) => `${d.date}: ${d.total}`).join('; ')
  return (
    <figure>
      <svg viewBox="0 0 280 120" role="img" aria-label={`Публикации за 7 дней. ${summary}`} className="h-40 w-full">
        {days.map((d, i) => {
          const x = 8 + i * 38
          const h = (d.total / max) * 84
          const ph = (d.published / max) * 84
          return (
            <g key={d.date}>
              <rect x={x} y={92 - h} width="26" height={Math.max(h, 2)} rx="4" className="fill-muted" />
              <rect x={x} y={92 - ph} width="26" height={ph} rx="4" className="fill-primary" />
              <text x={x + 13} y="108" textAnchor="middle" className="fill-muted-foreground text-[9px]">
                {d.date.slice(8)}
              </text>
              {d.total > 0 && (
                <text x={x + 13} y={86 - h} textAnchor="middle" className="fill-foreground text-[9px] font-medium">
                  {d.total}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      <figcaption className="mt-1 flex gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-primary" aria-hidden /> Опубликовано</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-muted" aria-hidden /> Всего создано</span>
      </figcaption>
    </figure>
  )
}

function DashboardSkeleton() {
  return (
    <div role="status" aria-label="Загрузка обзора" className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-24" />)}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
    </div>
  )
}

export function DashboardPage() {
  const { data, isLoading, isError, error, refetch } = useDashboard()
  const meta = useMeta()

  return (
    <>
      <PageHeader
        title="Обзор"
        description="Состояние подключённых аккаунтов и публикаций."
        actions={<Button asChild><Link to="/publish"><Send aria-hidden /> Новая публикация</Link></Button>}
      />
      {isLoading ? (
        <DashboardSkeleton />
      ) : isError || !data ? (
        <ErrorState message={errorMessage(error, 'Не удалось загрузить обзор')} onRetry={() => refetch()} />
      ) : (
        <div className="space-y-6">
          {data.accounts_needing_attention > 0 && (
            <Notice tone="warning" title="Нужно внимание">
              Доступ к {data.accounts_needing_attention} аккаунту(ам) TikTok недействителен.{' '}
              <Link className="font-medium underline underline-offset-4" to="/accounts">Переподключить</Link>
            </Notice>
          )}
          {meta.data && !meta.data.tiktok_client_audited && (
            <Notice tone="info" title="Приложение TikTok не прошло аудит">
              Публиковать можно только с видимостью «Только я» и в закрытые аккаунты — это ограничение TikTok для неаудированных приложений.
            </Notice>
          )}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Подключённые аккаунты" value={data.accounts_total} icon={<Users className="size-5" aria-hidden />} />
            <Stat label="В обработке" value={data.in_progress} icon={<Clock className="size-5" aria-hidden />} />
            <Stat label="Опубликовано за 7 дней" value={data.published_last_7_days} icon={<CheckCircle2 className="size-5" aria-hidden />} />
            <Stat label="Всего публикаций" value={data.publications_total} icon={<History className="size-5" aria-hidden />} />
          </div>

          {data.accounts_total === 0 ? (
            <EmptyState
              icon={Users}
              title="Подключите первый аккаунт TikTok"
              description="Это нужно, чтобы публиковать видео. Пароль TikTok мы не получаем — вход выполняется на официальной странице TikTok."
              action={<Button asChild><Link to="/accounts">Подключить TikTok</Link></Button>}
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>Активность за 7 дней</CardTitle>
                  <CardDescription>Созданные и успешно опубликованные видео</CardDescription>
                </CardHeader>
                <CardContent><ActivityChart daily={data.daily} /></CardContent>
              </Card>
              <Card>
                <CardHeader className="flex-row items-center justify-between">
                  <div className="space-y-1.5">
                    <CardTitle>Последние публикации</CardTitle>
                    <CardDescription>Пять недавних задач</CardDescription>
                  </div>
                  <Button asChild variant="ghost" size="sm"><Link to="/publications">Вся история</Link></Button>
                </CardHeader>
                <CardContent>
                  {data.recent.length === 0 ? (
                    <p className="py-6 text-center text-sm text-muted-foreground">Публикаций пока нет.</p>
                  ) : (
                    <ul className="divide-y">
                      {data.recent.map((p) => (
                        <li key={p.id}>
                          <Link to={`/publications/${p.id}`} className="flex items-center justify-between gap-3 py-3 hover:text-primary">
                            <span className="min-w-0">
                              <span className="block truncate text-sm font-medium">{p.title || 'Без описания'}</span>
                              <span className="block text-xs text-muted-foreground">
                                {formatRelative(p.created_at)} · {PRIVACY_LABEL[p.privacy_level]}
                              </span>
                            </span>
                            <PublicationStatusBadge status={p.status} />
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </>
  )
}
