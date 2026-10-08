import { ChevronLeft, ChevronRight, History, Send } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { EmptyState, ErrorState, PageHeader, PublicationStatusBadge } from '@/components/shared/common'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/services/http'
import { usePublications } from '@/services/queries'
import type { PublicationStatus } from '@/types/api'
import { formatDateTime } from '@/utils/format'
import { PRIVACY_LABEL, PUBLICATION_STATUS } from '@/utils/status'

const PAGE_SIZE = 10
const ALL = 'all'

export function PublicationsPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<PublicationStatus | typeof ALL>(ALL)
  const [offset, setOffset] = useState(0)
  const { data, isLoading, isError, error, refetch, isFetching } = usePublications({
    status: status === ALL ? undefined : status,
    limit: PAGE_SIZE,
    offset,
  })
  const total = data?.total ?? 0
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + PAGE_SIZE, total)

  return (
    <>
      <PageHeader
        title="История публикаций"
        description="Статусы обновляются автоматически, пока видео обрабатывается."
        actions={<Button asChild><Link to="/publish"><Send aria-hidden /> Новая публикация</Link></Button>}
      />
      <div className="mb-4 flex items-center gap-3">
        <label htmlFor="status-filter" className="text-sm text-muted-foreground">Статус</label>
        <div className="w-56">
          <Select value={status} onValueChange={(v) => { setStatus(v as typeof status); setOffset(0) }}>
            <SelectTrigger id="status-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Все</SelectItem>
              {(Object.keys(PUBLICATION_STATUS) as PublicationStatus[]).map((s) => (
                <SelectItem key={s} value={s}>{PUBLICATION_STATUS[s].label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {isLoading ? (
        <div role="status" aria-label="Загрузка истории" className="space-y-2">
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-16" />)}
        </div>
      ) : isError ? (
        <ErrorState message={errorMessage(error, 'Не удалось загрузить историю')} onRetry={() => refetch()} />
      ) : data && data.items.length === 0 ? (
        <EmptyState
          icon={History}
          title={status === ALL ? 'Публикаций пока нет' : 'Нет публикаций с таким статусом'}
          description={status === ALL ? 'Создайте первую публикацию — она появится здесь.' : 'Попробуйте выбрать другой статус.'}
          action={status === ALL ? <Button asChild><Link to="/publish">Создать публикацию</Link></Button> : undefined}
        />
      ) : (
        <Card className="overflow-hidden">
          <table className="hidden w-full text-sm md:table">
            <caption className="sr-only">Список публикаций</caption>
            <thead className="border-b bg-muted/50 text-left text-xs text-muted-foreground uppercase">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Описание</th>
                <th scope="col" className="px-4 py-3 font-medium">Видимость</th>
                <th scope="col" className="px-4 py-3 font-medium">Статус</th>
                <th scope="col" className="px-4 py-3 font-medium">Создано</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data?.items.map((p) => (
                <tr key={p.id} className="cursor-pointer hover:bg-accent/40" onClick={() => navigate(`/publications/${p.id}`)}>
                  <td className="max-w-xs px-4 py-3">
                    <Link to={`/publications/${p.id}`} className="block truncate font-medium hover:text-primary" onClick={(e) => e.stopPropagation()}>
                      {p.title || 'Без описания'}
                    </Link>
                    {p.fail_message && <span className="block truncate text-xs text-destructive">{p.fail_message}</span>}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{PRIVACY_LABEL[p.privacy_level]}</td>
                  <td className="px-4 py-3"><PublicationStatusBadge status={p.status} /></td>
                  <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">{formatDateTime(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="divide-y md:hidden">
            {data?.items.map((p) => (
              <li key={p.id}>
                <Link to={`/publications/${p.id}`} className="block space-y-1.5 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <span className="min-w-0 truncate font-medium">{p.title || 'Без описания'}</span>
                    <PublicationStatusBadge status={p.status} />
                  </div>
                  <p className="text-xs text-muted-foreground">{formatDateTime(p.created_at)} · {PRIVACY_LABEL[p.privacy_level]}</p>
                  {p.fail_message && <p className="text-xs text-destructive">{p.fail_message}</p>}
                </Link>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between border-t px-4 py-3 text-sm text-muted-foreground">
            <span aria-live="polite">{from}–{to} из {total}{isFetching ? ' · обновление…' : ''}</span>
            <div className="flex gap-1">
              <Button variant="outline" size="icon" aria-label="Предыдущая страница" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                <ChevronLeft aria-hidden />
              </Button>
              <Button variant="outline" size="icon" aria-label="Следующая страница" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                <ChevronRight aria-hidden />
              </Button>
            </div>
          </div>
        </Card>
      )}
    </>
  )
}
