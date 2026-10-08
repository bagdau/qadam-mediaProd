export type PrivacyLevel = 'PUBLIC_TO_EVERYONE' | 'MUTUAL_FOLLOW_FRIENDS' | 'FOLLOWER_OF_CREATOR' | 'SELF_ONLY'

export type PublicationStatus =
  | 'QUEUED'
  | 'INITIATING'
  | 'UPLOADING'
  | 'PROCESSING'
  | 'PUBLISHED'
  | 'INBOX_DELIVERED'
  | 'FAILED'
  | 'NEEDS_REVIEW'
  | 'CANCELLED'

export type PublicationMode = 'DIRECT_POST' | 'UPLOAD_TO_INBOX'
export type AccountStatus = 'active' | 'needs_reauth' | 'revoked'

export interface User {
  id: string
  email: string
  display_name: string
  role: 'admin' | 'member'
  created_at: string
  last_login_at: string | null
}

export interface AuthResponse {
  user: User
  csrf_token: string
}

export interface SessionInfo {
  id: string
  created_at: string
  last_seen_at: string
  expires_at: string
  ip_address: string | null
  user_agent: string | null
  current: boolean
}

export interface Account {
  id: string
  provider: string
  provider_account_id: string
  username: string | null
  display_name: string | null
  avatar_url: string | null
  scopes: string[]
  status: AccountStatus
  last_error: string | null
  connected_at: string
  access_expires_at: string | null
  refresh_expires_at: string | null
  last_refreshed_at: string | null
  disconnected_at: string | null
}

export interface CreatorInfo {
  username: string
  nickname: string
  avatar_url: string | null
  privacy_level_options: PrivacyLevel[]
  comment_disabled: boolean
  duet_disabled: boolean
  stitch_disabled: boolean
  max_video_post_duration_sec: number | null
}

export interface MediaAsset {
  id: string
  original_filename: string
  content_type: string
  size_bytes: number
  duration_seconds: number | null
  sha256: string
  status: string
  created_at: string
}

export interface Publication {
  id: string
  account_id: string
  media_id: string
  mode: PublicationMode
  status: PublicationStatus
  title: string
  privacy_level: PrivacyLevel
  disable_comment: boolean
  disable_duet: boolean
  disable_stitch: boolean
  brand_content_toggle: boolean
  brand_organic_toggle: boolean
  is_aigc: boolean
  tiktok_publish_id: string | null
  tiktok_post_ids: string[] | null
  uploaded_bytes: number
  attempts: number
  fail_reason: string | null
  fail_message: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
}

export interface PublicationEvent {
  id: string
  created_at: string
  type: string
  from_status: string | null
  to_status: string | null
  message: string
  details: Record<string, unknown> | null
}

export interface PublicationDetail extends Publication {
  events: PublicationEvent[]
  media_filename: string | null
  media_size_bytes: number | null
  account_username: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface PublicationCreate {
  account_id: string
  media_id: string
  mode: PublicationMode
  title: string
  privacy_level: PrivacyLevel
  allow_comment: boolean
  allow_duet: boolean
  allow_stitch: boolean
  brand_content_toggle: boolean
  brand_organic_toggle: boolean
  is_aigc: boolean
  music_usage_confirmed: boolean
  allow_duplicate?: boolean
}

export interface Meta {
  tiktok_configured: boolean
  tiktok_client_audited: boolean
  scopes: string[]
  max_video_mb: number
  allowed_content_types: string[]
  allow_registration: boolean
}

export interface Dashboard {
  accounts_total: number
  accounts_needing_attention: number
  publications_total: number
  publications_by_status: Partial<Record<PublicationStatus, number>>
  in_progress: number
  published_last_7_days: number
  daily: { date: string; total: number; published: number }[]
  recent: { id: string; title: string; status: PublicationStatus; created_at: string; privacy_level: PrivacyLevel }[]
}

export interface AuditLogEntry {
  id: string
  created_at: string
  action: string
  entity_type: string | null
  entity_id: string | null
  ip_address: string | null
  details: Record<string, unknown> | null
}
