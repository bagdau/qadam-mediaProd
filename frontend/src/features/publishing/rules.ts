import type { CreatorInfo, MediaAsset, PrivacyLevel, PublicationCreate, PublicationMode } from '@/types/api'
import { PRIVACY_LABEL } from '@/utils/status'

export const MAX_TITLE = 2200
export const ALLOWED_TYPES = ['video/mp4', 'video/quicktime', 'video/webm']

export interface PublishFormState {
  accountId: string
  mode: PublicationMode
  privacy: PrivacyLevel | ''
  title: string
  allowComment: boolean
  allowDuet: boolean
  allowStitch: boolean
  commercial: boolean
  brandOrganic: boolean // "Your brand"
  brandContent: boolean // "Branded content"
  isAigc: boolean
  musicConsent: boolean
}

/** TikTok guidelines: nothing is pre-selected, every toggle starts off. */
export const initialPublishState: PublishFormState = {
  accountId: '',
  mode: 'DIRECT_POST',
  privacy: '',
  title: '',
  allowComment: false,
  allowDuet: false,
  allowStitch: false,
  commercial: false,
  brandOrganic: false,
  brandContent: false,
  isAigc: false,
  musicConsent: false,
}

export interface PrivacyOption {
  value: PrivacyLevel
  label: string
  disabled: boolean
  reason?: string
}

/** Options exactly as returned by Creator Info, minus those that are not usable right now. */
export function privacyOptions(creator: CreatorInfo | undefined, audited: boolean, brandContent: boolean): PrivacyOption[] {
  if (!creator) return []
  return creator.privacy_level_options.map((value) => {
    if (!audited && value !== 'SELF_ONLY') {
      return { value, label: PRIVACY_LABEL[value], disabled: true, reason: 'Недоступно, пока приложение TikTok не прошло аудит' }
    }
    if (brandContent && value === 'SELF_ONLY') {
      return { value, label: PRIVACY_LABEL[value], disabled: true, reason: 'Брендированный контент нельзя публиковать «Только мне»' }
    }
    return { value, label: PRIVACY_LABEL[value], disabled: false }
  })
}

export interface ValidationResult {
  errors: Partial<Record<'account' | 'video' | 'privacy' | 'title' | 'commercial' | 'duration' | 'music', string>>
  canSubmit: boolean
}

export function validatePublish(
  state: PublishFormState,
  ctx: { creator: CreatorInfo | undefined; media: MediaAsset | null; audited: boolean },
): ValidationResult {
  const errors: ValidationResult['errors'] = {}
  const { creator, media, audited } = ctx
  const direct = state.mode === 'DIRECT_POST'

  if (!state.accountId) errors.account = 'Выберите аккаунт TikTok'
  if (!media) errors.video = 'Загрузите видео'
  if (state.title.length > MAX_TITLE) errors.title = `Не больше ${MAX_TITLE} символов`

  if (direct) {
    if (!state.privacy) errors.privacy = 'Выберите, кто увидит видео'
    else if (creator && !creator.privacy_level_options.includes(state.privacy)) errors.privacy = 'Этот вариант недоступен для аккаунта'
    else if (!audited && state.privacy !== 'SELF_ONLY') errors.privacy = 'Пока приложение не аудировано, доступно только «Только я»'
    if (state.commercial) {
      if (!state.brandOrganic && !state.brandContent) errors.commercial = 'Укажите, что вы продвигаете: себя, третье лицо или и то и другое'
      else if (state.brandContent && state.privacy === 'SELF_ONLY') errors.commercial = 'Брендированный контент нельзя опубликовать с видимостью «Только я»'
    }
    if (!state.musicConsent) errors.music = 'Подтвердите согласие с условиями TikTok'
  }

  const max = creator?.max_video_post_duration_sec
  if (direct && max && media?.duration_seconds && media.duration_seconds > max + 0.5) {
    errors.duration = `Этот аккаунт может публиковать видео не длиннее ${max} с`
  }
  if (direct && creator && creator.privacy_level_options.length === 0) {
    errors.account = 'Этот аккаунт TikTok сейчас не может публиковать. Повторите позже.'
  }
  return { errors, canSubmit: Object.keys(errors).length === 0 && !!creator }
}

export function toPayload(state: PublishFormState, mediaId: string, creator: CreatorInfo): PublicationCreate {
  const direct = state.mode === 'DIRECT_POST'
  return {
    account_id: state.accountId,
    media_id: mediaId,
    mode: state.mode,
    title: state.title,
    privacy_level: direct ? (state.privacy as PrivacyLevel) : 'SELF_ONLY',
    // creator-level restrictions always win over what the form says
    allow_comment: direct && state.allowComment && !creator.comment_disabled,
    allow_duet: direct && state.allowDuet && !creator.duet_disabled,
    allow_stitch: direct && state.allowStitch && !creator.stitch_disabled,
    brand_content_toggle: direct && state.commercial && state.brandContent,
    brand_organic_toggle: direct && state.commercial && state.brandOrganic,
    is_aigc: state.isAigc,
    music_usage_confirmed: direct ? state.musicConsent : false,
  }
}

export interface ClientFileCheck {
  ok: boolean
  error?: string
}

export function checkFile(file: { type: string; size: number; name: string }, maxMb: number): ClientFileCheck {
  const byExt = /\.(mp4|mov|webm)$/i.test(file.name)
  if (!ALLOWED_TYPES.includes(file.type) && !(file.type === '' && byExt)) return { ok: false, error: 'Поддерживаются только MP4, MOV и WebM' }
  if (file.size === 0) return { ok: false, error: 'Файл пустой' }
  if (file.size > maxMb * 1024 * 1024) return { ok: false, error: `Файл больше ${maxMb} МБ` }
  return { ok: true }
}

/** Short summary shown in the confirmation dialog. */
export function summarise(state: PublishFormState, creator: CreatorInfo): string {
  if (state.mode === 'UPLOAD_TO_INBOX') return `Видео будет отправлено в черновики @${creator.username}`
  return `Видео будет опубликовано в @${creator.username} · ${state.privacy ? PRIVACY_LABEL[state.privacy] : ''}`
}
