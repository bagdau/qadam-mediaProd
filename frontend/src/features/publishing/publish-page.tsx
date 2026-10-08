import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Send, Users } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Controller, useForm, type Resolver } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'
import { EmptyState, ErrorState, Notice, PageHeader } from '@/components/shared/common'
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
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { publicationsApi } from '@/services/api'
import { ApiError, errorMessage } from '@/services/http'
import { keys, useAccounts, useCreatorInfo, useMeta } from '@/services/queries'
import type { MediaAsset } from '@/types/api'
import { newIdempotencyKey } from '@/utils/format'
import { MAX_TITLE, initialPublishState, privacyOptions, summarise, toPayload, validatePublish, type PublishFormState } from './rules'
import { VideoUploader } from './video-uploader'

const FIELD_PATH: Record<string, keyof PublishFormState> = {
  account: 'accountId',
  privacy: 'privacy',
  title: 'title',
  commercial: 'brandContent',
  music: 'musicConsent',
}

interface ResolverContext {
  creator: ReturnType<typeof useCreatorInfo>['data']
  media: MediaAsset | null
  audited: boolean
}

/** Single source of truth for validation: the pure rules in rules.ts, surfaced through Zod. */
function buildResolver(ctxRef: { current: ResolverContext }): Resolver<PublishFormState> {
  return (values, context, options) => {
    const schema = z.custom<PublishFormState>().superRefine((v, zctx) => {
      const { errors } = validatePublish(v, ctxRef.current)
      for (const [key, message] of Object.entries(errors)) {
        const path = FIELD_PATH[key]
        if (path) zctx.addIssue({ code: 'custom', message, path: [path] })
        else zctx.addIssue({ code: 'custom', message, path: ['_form'] })
      }
    })
    return zodResolver(schema as never)(values, context, options as never) as never
  }
}

function ToggleRow({
  id,
  label,
  description,
  checked,
  onChange,
  disabled,
  disabledReason,
}: {
  id: string
  label: string
  description?: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
  disabledReason?: string
}) {
  const row = (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="min-w-0">
        <Label htmlFor={id} className={disabled ? 'text-muted-foreground' : undefined}>{label}</Label>
        {(disabled ? disabledReason : description) && (
          <p className="mt-1 text-xs text-muted-foreground">{disabled ? disabledReason : description}</p>
        )}
      </div>
      <Switch id={id} checked={checked && !disabled} onCheckedChange={onChange} disabled={disabled} />
    </div>
  )
  if (!disabled || !disabledReason) return row
  return (
    <Tooltip>
      <TooltipTrigger asChild><div>{row}</div></TooltipTrigger>
      <TooltipContent>{disabledReason}</TooltipContent>
    </Tooltip>
  )
}

export function PublishPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const accountsQuery = useAccounts()
  const meta = useMeta()
  const audited = meta.data?.tiktok_client_audited ?? false
  const [media, setMedia] = useState<MediaAsset | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const idempotencyKey = useRef(newIdempotencyKey())

  const active = useMemo(() => (accountsQuery.data ?? []).filter((a) => a.status === 'active'), [accountsQuery.data])
  const ctxRef = useRef<ResolverContext>({ creator: undefined, media: null, audited })
  const resolver = useMemo(() => buildResolver(ctxRef), [])
  const form = useForm<PublishFormState>({ defaultValues: initialPublishState, resolver, mode: 'onChange' })
  const { control, watch, setValue, trigger, formState } = form
  const values = watch()

  const creatorQuery = useCreatorInfo(values.accountId || undefined)
  const creator = creatorQuery.data
  ctxRef.current = { creator, media, audited }

  // single connected account -> preselect it (an account is not a "choice" the guidelines forbid defaulting)
  useEffect(() => {
    if (!values.accountId && active.length === 1) setValue('accountId', active[0].id, { shouldValidate: true })
  }, [active, values.accountId, setValue])

  // Re-validate and reconcile with creator restrictions whenever the inputs of the rules change.
  useEffect(() => {
    if (creator) {
      if (creator.comment_disabled) setValue('allowComment', false)
      if (creator.duet_disabled) setValue('allowDuet', false)
      if (creator.stitch_disabled) setValue('allowStitch', false)
      if (values.privacy && !creator.privacy_level_options.includes(values.privacy)) setValue('privacy', '')
    }
    void trigger()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creator, media, audited])

  useEffect(() => {
    // branded content cannot be private (guideline): drop an incompatible selection
    if (values.commercial && values.brandContent && values.privacy === 'SELF_ONLY') setValue('privacy', '', { shouldValidate: true })
  }, [values.commercial, values.brandContent, values.privacy, setValue])

  const direct = values.mode === 'DIRECT_POST'
  const options = privacyOptions(creator, audited, values.commercial && values.brandContent)
  const { errors: ruleErrors } = validatePublish(values, ctxRef.current)
  const canSubmit = formState.isValid && !!creator && !!media && !creatorQuery.isFetching
  const account = active.find((a) => a.id === values.accountId)
  const inboxAllowed = !!account?.scopes.includes('video.upload')

  const submit = useMutation({
    mutationFn: () => publicationsApi.create(toPayload(values, media!.id, creator!), idempotencyKey.current),
    onSuccess: (pub) => {
      toast.success('Публикация поставлена в очередь')
      idempotencyKey.current = newIdempotencyKey()
      qc.invalidateQueries({ queryKey: ['publications'] })
      qc.invalidateQueries({ queryKey: keys.dashboard })
      navigate(`/publications/${pub.id}`)
    },
    onError: (e) => {
      setConfirmOpen(false)
      // A rejected request created nothing, so a fresh key is safe. Network/5xx outcomes are unknown: keep the key.
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) idempotencyKey.current = newIdempotencyKey()
      if (e instanceof ApiError && e.code === 'duplicate_publication') toast.error('Это видео уже публиковалось в этот аккаунт. Загрузите другое видео.')
      else toast.error(errorMessage(e, 'Не удалось создать публикацию'))
    },
  })

  if (accountsQuery.isLoading || meta.isLoading) {
    return (
      <>
        <PageHeader title="Новая публикация" />
        <div role="status" aria-label="Загрузка формы" className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-72" /></div>
      </>
    )
  }
  if (accountsQuery.isError) {
    return <ErrorState message={errorMessage(accountsQuery.error, 'Не удалось загрузить аккаунты')} onRetry={() => accountsQuery.refetch()} />
  }
  if (active.length === 0) {
    return (
      <>
        <PageHeader title="Новая публикация" />
        <EmptyState
          icon={Users}
          title="Нет подключённого аккаунта"
          description="Чтобы опубликовать видео, подключите аккаунт TikTok."
          action={<Button asChild><Link to="/accounts">Перейти к аккаунтам</Link></Button>}
        />
      </>
    )
  }

  return (
    <>
      <PageHeader title="Новая публикация" description="Загрузите видео, проверьте параметры и отправьте в TikTok." />
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit) setConfirmOpen(true)
        }}
        className="grid gap-6 lg:grid-cols-[1fr_20rem]"
      >
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>1. Аккаунт и видео</CardTitle>
              <CardDescription>Куда публикуем и что именно</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="account">Аккаунт TikTok</Label>
                <Controller
                  control={control}
                  name="accountId"
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger id="account" aria-invalid={!!formState.errors.accountId}>
                        <SelectValue placeholder="Выберите аккаунт" />
                      </SelectTrigger>
                      <SelectContent>
                        {active.map((a) => <SelectItem key={a.id} value={a.id}>{a.display_name || a.username || 'TikTok'}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  )}
                />
                {values.accountId && creatorQuery.isLoading && <Skeleton className="h-5 w-56" />}
                {creator && (
                  <p className="text-sm text-muted-foreground">
                    Публикация пойдёт в <span className="font-medium text-foreground">@{creator.username || creator.nickname}</span>
                    {creator.max_video_post_duration_sec ? ` · максимум ${Math.round(creator.max_video_post_duration_sec / 60)} мин` : ''}
                  </p>
                )}
                {creatorQuery.isError && (
                  <ErrorState message={errorMessage(creatorQuery.error, 'Не удалось получить параметры аккаунта')} onRetry={() => creatorQuery.refetch()} />
                )}
                {creator && creator.privacy_level_options.length === 0 && (
                  <Notice tone="warning">Этот аккаунт сейчас не может публиковать видео (лимит TikTok). Повторите позже.</Notice>
                )}
              </div>

              <div className="space-y-2">
                <Label>Видео</Label>
                <VideoUploader
                  maxMb={meta.data?.max_video_mb ?? 512}
                  media={media}
                  onChange={setMedia}
                  disabled={submit.isPending}
                  error={ruleErrors.duration}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>2. Параметры публикации</CardTitle>
              <CardDescription>Ничего не выбрано заранее — решение за вами</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Способ</legend>
                <Controller
                  control={control}
                  name="mode"
                  render={({ field }) => (
                    <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Способ отправки">
                      {([
                        ['DIRECT_POST', 'Опубликовать сразу', 'Видео появится в профиле сразу после обработки'],
                        ['UPLOAD_TO_INBOX', 'В черновики TikTok', 'Завершите публикацию в приложении TikTok'],
                      ] as const).map(([value, title, hint]) => {
                        const disabled = value === 'UPLOAD_TO_INBOX' && !inboxAllowed
                        return (
                          <label key={value} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${field.value === value ? 'border-primary bg-accent/40' : ''} ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}>
                            <input type="radio" className="mt-1 accent-[var(--primary)]" name="mode" value={value} checked={field.value === value}
                              disabled={disabled} onChange={() => field.onChange(value)} />
                            <span>
                              <span className="block text-sm font-medium">{title}</span>
                              <span className="block text-xs text-muted-foreground">{disabled ? 'Нет разрешения video.upload — переподключите аккаунт' : hint}</span>
                            </span>
                          </label>
                        )
                      })}
                    </div>
                  )}
                />
              </fieldset>

              <div className="space-y-2">
                <div className="flex items-baseline justify-between">
                  <Label htmlFor="title">Описание</Label>
                  <span className={`text-xs tabular-nums ${values.title.length > MAX_TITLE ? 'text-destructive' : 'text-muted-foreground'}`}>
                    {values.title.length}/{MAX_TITLE}
                  </span>
                </div>
                <Controller
                  control={control}
                  name="title"
                  render={({ field }) => (
                    <Textarea id="title" rows={4} placeholder="Текст публикации, хэштеги, упоминания…" aria-invalid={!!formState.errors.title} {...field} />
                  )}
                />
                {formState.errors.title && <p role="alert" className="text-sm text-destructive">{formState.errors.title.message}</p>}
              </div>

              {direct && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="privacy">Кто может смотреть это видео</Label>
                    <Controller
                      control={control}
                      name="privacy"
                      render={({ field }) => (
                        <Select value={field.value} onValueChange={field.onChange} disabled={!creator}>
                          <SelectTrigger id="privacy" aria-invalid={!!formState.errors.privacy}>
                            <SelectValue placeholder={creator ? 'Выберите вариант' : 'Сначала выберите аккаунт'} />
                          </SelectTrigger>
                          <SelectContent>
                            {options.map((o) => (
                              <SelectItem key={o.value} value={o.value} disabled={o.disabled}>
                                {o.label}{o.disabled && o.reason ? ` — ${o.reason}` : ''}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    />
                    {formState.errors.privacy && formState.touchedFields.privacy && (
                      <p role="alert" className="text-sm text-destructive">{formState.errors.privacy.message}</p>
                    )}
                  </div>

                  <div className="divide-y rounded-lg border px-4" role="group" aria-label="Взаимодействия">
                    <Controller control={control} name="allowComment" render={({ field }) => (
                      <ToggleRow id="allow-comment" label="Разрешить комментарии" checked={field.value} onChange={field.onChange}
                        disabled={creator?.comment_disabled} disabledReason="Отключено в настройках вашего аккаунта TikTok" />
                    )} />
                    <Controller control={control} name="allowDuet" render={({ field }) => (
                      <ToggleRow id="allow-duet" label="Разрешить Duet" checked={field.value} onChange={field.onChange}
                        disabled={creator?.duet_disabled} disabledReason="Отключено в настройках аккаунта TikTok или аккаунт закрытый" />
                    )} />
                    <Controller control={control} name="allowStitch" render={({ field }) => (
                      <ToggleRow id="allow-stitch" label="Разрешить Stitch" checked={field.value} onChange={field.onChange}
                        disabled={creator?.stitch_disabled} disabledReason="Отключено в настройках аккаунта TikTok или аккаунт закрытый" />
                    )} />
                  </div>

                  <div className="rounded-lg border px-4 py-2">
                    <Controller control={control} name="commercial" render={({ field }) => (
                      <ToggleRow id="commercial" label="Раскрыть коммерческий контент" description="Включите, если видео продвигает вас, бренд или товар"
                        checked={field.value} onChange={(v) => { field.onChange(v); if (!v) { setValue('brandOrganic', false); setValue('brandContent', false) } }} />
                    )} />
                    {values.commercial && (
                      <div className="space-y-3 border-t py-3">
                        <div className="flex items-start gap-3">
                          <Controller control={control} name="brandOrganic" render={({ field }) => (
                            <Checkbox id="brand-organic" checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} />
                          )} />
                          <Label htmlFor="brand-organic" className="leading-snug">Ваш бренд <span className="block text-xs font-normal text-muted-foreground">Вы продвигаете себя или свой бизнес — публикация получит метку «Рекламный контент»</span></Label>
                        </div>
                        <div className="flex items-start gap-3">
                          <Controller control={control} name="brandContent" render={({ field }) => (
                            <Checkbox id="brand-content" checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} />
                          )} />
                          <Label htmlFor="brand-content" className="leading-snug">Брендированный контент <span className="block text-xs font-normal text-muted-foreground">Вы продвигаете другой бренд или третье лицо — метка «Платное партнёрство»</span></Label>
                        </div>
                        {ruleErrors.commercial && <p role="alert" className="text-sm text-destructive">{ruleErrors.commercial}</p>}
                        {values.brandContent && values.brandOrganic && <p className="text-xs text-muted-foreground">Будет показана метка «Платное партнёрство».</p>}
                      </div>
                    )}
                  </div>

                  <Controller control={control} name="isAigc" render={({ field }) => (
                    <div className="rounded-lg border px-4">
                      <ToggleRow id="aigc" label="Контент создан с помощью ИИ" description="TikTok пометит видео как созданное ИИ" checked={field.value} onChange={field.onChange} />
                    </div>
                  )} />
                </>
              )}
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <Card>
            <CardHeader><CardTitle>Проверка</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              {!audited && direct && (
                <Notice tone="info">Приложение не прошло аудит TikTok: доступна только видимость «Только я», аккаунт должен быть закрытым.</Notice>
              )}
              {direct && (
                <div className="flex items-start gap-3">
                  <Controller control={control} name="musicConsent" render={({ field }) => (
                    <Checkbox id="music" checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} aria-describedby="music-hint" />
                  )} />
                  <div>
                    <Label htmlFor="music" className="leading-snug font-normal">
                      Публикуя, вы соглашаетесь с{' '}
                      <a className="underline underline-offset-4" href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en" target="_blank" rel="noreferrer noopener">
                        Music Usage Confirmation
                      </a>{' '}TikTok
                      {values.commercial && values.brandContent && (
                        <> и{' '}
                          <a className="underline underline-offset-4" href="https://www.tiktok.com/legal/page/global/bc-policy/en" target="_blank" rel="noreferrer noopener">
                            Branded Content Policy
                          </a></>
                      )}
                      .
                    </Label>
                    <p id="music-hint" className="sr-only">Обязательное подтверждение для публикации</p>
                  </div>
                </div>
              )}
              <ul className="space-y-1.5 text-sm" aria-label="Что нужно исправить">
                {Object.values(ruleErrors).map((message) => (
                  <li key={message} className="flex items-start gap-2 text-muted-foreground">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden /> {message}
                  </li>
                ))}
              </ul>
              <Button type="submit" className="w-full" size="lg" disabled={!canSubmit} loading={submit.isPending}>
                <Send aria-hidden /> {direct ? 'Опубликовать' : 'Отправить в черновики'}
              </Button>
            </CardContent>
          </Card>
        </aside>
      </form>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Отправить видео в TikTok?</AlertDialogTitle>
            <AlertDialogDescription>
              {creator ? summarise(values, creator) : ''}. {media ? `Файл: ${media.original_filename}.` : ''} Действие нельзя отменить после начала загрузки.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Назад</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault() // keep the dialog open while the request runs
                submit.mutate()
              }}
              disabled={submit.isPending}
            >
              {submit.isPending ? 'Отправляем…' : 'Да, отправить'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
