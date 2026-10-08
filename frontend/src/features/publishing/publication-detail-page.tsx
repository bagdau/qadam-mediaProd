import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, CircleAlert, ExternalLink, Loader2, RotateCcw, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState, Notice, PageHeader, PublicationStatusBadge } from '@/components/shared/common'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { publicationsApi } from '@/services/api'
import { ApiError, errorMessage } from '@/services/http'
import { keys, usePublication } from '@/services/queries'
import type { PublicationDetail, PublicationStatus } from '@/types/api'
import { cn } from '@/utils/cn'
import { formatBytes, formatDateTime } from '@/utils/format'
import { PIPELINE, PRIVACY_LABEL, PUBLICATION_STATUS, isActiveStatus } from '@/utils/status'

const STEP_LABEL: Record<string, string> = { QUEUED: 'В очереди', UPLOADING: 'Загрузка в TikTok', PROCESSING: 'Обработка TikTok', PUBLISHED: 'Опубликовано' }

/** Index of the pipeline step that is current for a status (INITIATING belongs to the first step, inbox delivery to the last). */
export function stepIndex(status: PublicationStatus): number {
  if (status === 'INITIATING') return 1
  if (status === 'INBOX_DELIVERED') return PIPELINE.length - 1
  const i = PIPELINE.indexOf(status)
  return i === -1 ? 0 : i
}

function Stepper({ pub }: { pub: PublicationDetail }) {
  const failed = pub.status === 'FAILED' || pub.status === 'NEEDS_REVIEW' || pub.status === 'CANCELLED'
  const current = failed ? Math.max(0, stepIndexFromEvents(pub)) : stepIndex(pub.status)
  const done = pub.status === 'PUBLISHED' || pub.status === 'INBOX_DELIVERED'
  return (
    <ol className="grid grid-cols-4 gap-2" aria-label="Этапы публикации">
      {PIPELINE.map((step, i) => {
        const complete = done || i < current
        const isCurrent = i === current && !done && !failed
        const broken = failed && i === current
        return (
          <li key={step} className="flex flex-col items-center gap-2 text-center" aria-current={isCurrent ? 'step' : undefined}>
            <span
              className={cn(
                'flex size-9 items-center justify-center rounded-full border-2 text-sm font-semibold',
                complete && 'border-success bg-success text-background',
                isCurrent && 'border-primary text-primary',
                broken && 'border-destructive text-destructive',
                !complete && !isCurrent && !broken && 'border-border text-muted-foreground',
              )}
            >
              {complete ? <Check className="size-4" aria-hidden /> : broken ? <XCircle className="size-4" aria-hidden /> : isCurrent ? <Loader2 className="size-4 animate-spin" aria-hidden /> : i + 1}
            </span>
            <span className={cn('text-xs', isCurrent || complete ? 'font-medium' : 'text-muted-foreground')}>
              {step === 'PUBLISHED' && pub.status === 'INBOX_DELIVERED' ? 'В черновиках' : STEP_LABEL[step]}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function stepIndexFromEvents(pub: PublicationDetail): number {
  // furthest step reached before the failure
  const reached = pub.events.map((e) => e.to_status).filter(Boolean) as string[]
  if (reached.includes('PROCESSING')) return 2
  if (reached.includes('UPLOADING')) return 1
  return 0
}

export function PublicationDetailPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const { data: pub, isLoading, isError, error, refetch } = usePublication(id)
  const [riskDialog, setRiskDialog] = useState(false)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: keys.publication(id) })
    qc.invalidateQueries({ queryKey: ['publications'] })
    qc.invalidateQueries({ queryKey: keys.dashboard })
  }
  const cancel = useMutation({
    mutationFn: () => publicationsApi.cancel(id),
    onSuccess: () => { toast.success('Публикация отменена'); invalidate() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const retry = useMutation({
    mutationFn: (confirm: boolean) => publicationsApi.retry(id, confirm),
    onSuccess: () => { toast.success('Публикация отправлена повторно'); setRiskDialog(false); invalidate() },
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'duplicate_risk') setRiskDialog(true)
      else toast.error(errorMessage(e))
    },
  })

  if (isLoading) {
    return <div role="status" aria-label="Загрузка публикации" className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-40" /><Skeleton className="h-64" /></div>
  }
  if (isError || !pub) {
    const notFound = error instanceof ApiError && error.status === 404
    return <ErrorState message={notFound ? 'Публикация не найдена' : errorMessage(error, 'Не удалось загрузить публикацию')} onRetry={notFound ? undefined : () => refetch()} />
  }

  const active = isActiveStatus(pub.status)
  const meta = PUBLICATION_STATUS[pub.status]
  const uploadPercent = pub.media_size_bytes ? Math.min(100, Math.round((pub.uploaded_bytes / pub.media_size_bytes) * 100)) : 0

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-3 -ml-2"><Link to="/publications"><ArrowLeft aria-hidden /> К истории</Link></Button>
      <PageHeader
        title={pub.title || 'Публикация без описания'}
        description={`${pub.account_username ?? 'TikTok'} · ${PRIVACY_LABEL[pub.privacy_level]} · создана ${formatDateTime(pub.created_at)}`}
        actions={
          <>
            {pub.status === 'QUEUED' && (
              <Button variant="outline" onClick={() => cancel.mutate()} loading={cancel.isPending}>Отменить</Button>
            )}
            {(pub.status === 'FAILED' || pub.status === 'NEEDS_REVIEW') && (
              <Button onClick={() => retry.mutate(false)} loading={retry.isPending}><RotateCcw aria-hidden /> Повторить</Button>
            )}
          </>
        }
      />

      <div className="space-y-6" aria-live="polite">
        {pub.status === 'FAILED' && (
          <Notice tone="warning" title="Публикация не удалась">{pub.fail_message ?? 'TikTok отклонил публикацию.'}</Notice>
        )}
        {pub.status === 'NEEDS_REVIEW' && (
          <Notice tone="warning" title="Нужна ручная проверка">
            {pub.fail_message} Откройте приложение TikTok и проверьте профиль и черновики: если видео там есть, повторять публикацию не нужно.
          </Notice>
        )}
        {(pub.status === 'PUBLISHED' || pub.status === 'INBOX_DELIVERED') && (
          <Notice tone="success" title={meta.label}>
            {pub.status === 'PUBLISHED'
              ? 'TikTok подтвердил публикацию.'
              : 'Откройте приложение TikTok → черновики, чтобы завершить публикацию.'}
            {pub.tiktok_post_ids?.length ? <span className="mt-1 flex items-center gap-1 text-xs text-muted-foreground"><ExternalLink className="size-3" aria-hidden /> ID поста: {pub.tiktok_post_ids.join(', ')}</span> : null}
          </Notice>
        )}

        <Card>
          <CardHeader className="flex-row items-center justify-between gap-3">
            <div className="space-y-1.5">
              <CardTitle>Статус</CardTitle>
              <CardDescription>{meta.description}</CardDescription>
            </div>
            <PublicationStatusBadge status={pub.status} />
          </CardHeader>
          <CardContent className="space-y-5">
            <Stepper pub={pub} />
            {pub.status === 'UPLOADING' && (
              <div className="space-y-1.5">
                <Progress value={uploadPercent} aria-label="Прогресс загрузки в TikTok" />
                <p className="text-xs text-muted-foreground">{formatBytes(pub.uploaded_bytes)} из {formatBytes(pub.media_size_bytes ?? 0)}</p>
              </div>
            )}
            {active && <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" aria-hidden /> Страница обновляется автоматически</p>}
          </CardContent>
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Параметры</CardTitle></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                <dt className="text-muted-foreground">Видео</dt><dd className="truncate">{pub.media_filename ?? '—'}</dd>
                <dt className="text-muted-foreground">Размер</dt><dd>{pub.media_size_bytes ? formatBytes(pub.media_size_bytes) : '—'}</dd>
                <dt className="text-muted-foreground">Режим</dt><dd>{pub.mode === 'DIRECT_POST' ? 'Прямая публикация' : 'В черновики'}</dd>
                <dt className="text-muted-foreground">Комментарии</dt><dd>{pub.disable_comment ? 'Выключены' : 'Разрешены'}</dd>
                <dt className="text-muted-foreground">Duet</dt><dd>{pub.disable_duet ? 'Выключен' : 'Разрешён'}</dd>
                <dt className="text-muted-foreground">Stitch</dt><dd>{pub.disable_stitch ? 'Выключен' : 'Разрешён'}</dd>
                <dt className="text-muted-foreground">Коммерческий контент</dt>
                <dd>{pub.brand_content_toggle ? 'Платное партнёрство' : pub.brand_organic_toggle ? 'Ваш бренд' : 'Нет'}</dd>
                <dt className="text-muted-foreground">Попыток</dt><dd>{pub.attempts}</dd>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>История событий</CardTitle></CardHeader>
            <CardContent>
              <ol className="space-y-4 border-l pl-4">
                {pub.events.map((e) => (
                  <li key={e.id} className="relative">
                    <span className="absolute top-1.5 -left-[1.3rem] size-2.5 rounded-full bg-primary" aria-hidden />
                    <p className="text-sm">
                      {e.to_status ? <span className="font-medium">{PUBLICATION_STATUS[e.to_status as PublicationStatus]?.label ?? e.to_status}</span> : <span className="font-medium">{e.type === 'retry_scheduled' ? 'Повтор запланирован' : e.type === 'tiktok_status' ? 'Ответ TikTok' : 'Событие'}</span>}
                      {e.message && e.type !== 'tiktok_status' ? <span className="text-muted-foreground"> — {e.message}</span> : null}
                    </p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(e.created_at)}</p>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </div>
      </div>

      <AlertDialog open={riskDialog} onOpenChange={setRiskDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2"><CircleAlert className="size-5 text-warning" aria-hidden /> Возможен дубль</AlertDialogTitle>
            <AlertDialogDescription>
              Мы не получили подтверждения, принял ли TikTok предыдущий запрос. Проверьте профиль и черновики в приложении TikTok. Если видео там уже есть,
              повтор создаст второй пост.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Не повторять</AlertDialogCancel>
            <AlertDialogAction onClick={(e) => { e.preventDefault(); retry.mutate(true) }}>Видео нет — повторить</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
