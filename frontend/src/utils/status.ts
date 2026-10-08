import type { AccountStatus, PrivacyLevel, PublicationStatus } from '@/types/api'

type BadgeVariant = 'default' | 'secondary' | 'outline' | 'success' | 'warning' | 'info' | 'destructive'

export const PUBLICATION_STATUS: Record<PublicationStatus, { label: string; variant: BadgeVariant; description: string }> = {
  QUEUED: { label: 'В очереди', variant: 'secondary', description: 'Ожидает обработки воркером' },
  INITIATING: { label: 'Запуск', variant: 'info', description: 'Отправляем запрос на публикацию в TikTok' },
  UPLOADING: { label: 'Загрузка', variant: 'info', description: 'Видео передаётся в TikTok' },
  PROCESSING: { label: 'Обработка', variant: 'info', description: 'TikTok обрабатывает видео' },
  PUBLISHED: { label: 'Опубликовано', variant: 'success', description: 'Видео опубликовано' },
  INBOX_DELIVERED: { label: 'В черновиках', variant: 'success', description: 'Видео в черновиках TikTok' },
  FAILED: { label: 'Ошибка', variant: 'destructive', description: 'Публикация не удалась' },
  NEEDS_REVIEW: { label: 'Нужна проверка', variant: 'warning', description: 'Результат неизвестен — проверьте TikTok' },
  CANCELLED: { label: 'Отменено', variant: 'outline', description: 'Отменено пользователем' },
}

const ACTIVE: PublicationStatus[] = ['QUEUED', 'INITIATING', 'UPLOADING', 'PROCESSING']
export const isActiveStatus = (s: PublicationStatus) => ACTIVE.includes(s)

export const PIPELINE: PublicationStatus[] = ['QUEUED', 'UPLOADING', 'PROCESSING', 'PUBLISHED']

export const ACCOUNT_STATUS: Record<AccountStatus, { label: string; variant: BadgeVariant }> = {
  active: { label: 'Подключён', variant: 'success' },
  needs_reauth: { label: 'Нужно переподключить', variant: 'warning' },
  revoked: { label: 'Отключён', variant: 'outline' },
}

export const PRIVACY_LABEL: Record<PrivacyLevel, string> = {
  PUBLIC_TO_EVERYONE: 'Все',
  MUTUAL_FOLLOW_FRIENDS: 'Друзья (взаимные подписки)',
  FOLLOWER_OF_CREATOR: 'Подписчики',
  SELF_ONLY: 'Только я',
}

export const AUDIT_ACTION_LABEL: Record<string, string> = {
  'auth.login': 'Вход в систему',
  'auth.login_failed': 'Неудачная попытка входа',
  'auth.logout': 'Выход',
  'auth.password_changed': 'Смена пароля',
  'auth.session_revoked': 'Сессия завершена',
  'tiktok.oauth_started': 'Начато подключение TikTok',
  'tiktok.account_connected': 'TikTok-аккаунт подключён',
  'tiktok.account_disconnected': 'TikTok-аккаунт отключён',
  'tiktok.oauth_denied': 'Доступ TikTok отклонён',
  'tiktok.reauth_required': 'Требуется переподключение TikTok',
  'media.uploaded': 'Видео загружено',
  'media.deleted': 'Видео удалено',
  'publication.created': 'Публикация создана',
  'publication.cancelled': 'Публикация отменена',
  'publication.retried': 'Публикация перезапущена',
}
