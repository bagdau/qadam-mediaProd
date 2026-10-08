import { QueryClient } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { RouterProvider } from 'react-router-dom'
import { AppProviders } from '@/app/providers'
import { createTestRouter } from '@/app/router'
import type { Account, AuthResponse, CreatorInfo, Meta, MediaAsset, Publication, PublicationDetail } from '@/types/api'

export function renderApp(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } })
  const router = createTestRouter([path])
  const utils = render(
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>,
  )
  return { ...utils, router, client }
}

export const authUser: AuthResponse = {
  csrf_token: 'csrf',
  user: {
    id: 'u1',
    email: 'owner@example.com',
    display_name: 'Owner',
    role: 'member',
    created_at: '2026-10-01T10:00:00Z',
    last_login_at: '2026-10-08T10:00:00Z',
  },
}

export const account: Account = {
  id: 'a1',
  provider: 'tiktok',
  provider_account_id: 'open-1',
  username: 'tester',
  display_name: 'Test Creator',
  avatar_url: null,
  scopes: ['user.info.basic', 'video.publish', 'video.upload'],
  status: 'active',
  last_error: null,
  connected_at: '2026-10-01T10:00:00Z',
  access_expires_at: '2026-10-10T10:00:00Z',
  refresh_expires_at: '2027-10-01T10:00:00Z',
  last_refreshed_at: null,
  disconnected_at: null,
}

export const creator: CreatorInfo = {
  username: 'tester',
  nickname: 'Test Creator',
  avatar_url: null,
  privacy_level_options: ['PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY'],
  comment_disabled: false,
  duet_disabled: false,
  stitch_disabled: false,
  max_video_post_duration_sec: 600,
}

export const meta: Meta = {
  tiktok_configured: true,
  tiktok_client_audited: false,
  scopes: ['user.info.basic', 'video.publish'],
  max_video_mb: 512,
  allowed_content_types: ['video/mp4', 'video/quicktime', 'video/webm'],
  allow_registration: false,
}

export const media: MediaAsset = {
  id: 'm1',
  original_filename: 'promo.mp4',
  content_type: 'video/mp4',
  size_bytes: 5_000_000,
  duration_seconds: 30,
  sha256: 'a'.repeat(64),
  status: 'ready',
  created_at: '2026-10-09T10:00:00Z',
}

export const publication: Publication = {
  id: 'p1',
  account_id: 'a1',
  media_id: 'm1',
  mode: 'DIRECT_POST',
  status: 'PUBLISHED',
  title: 'Launch day #qadam',
  privacy_level: 'SELF_ONLY',
  disable_comment: true,
  disable_duet: true,
  disable_stitch: true,
  brand_content_toggle: false,
  brand_organic_toggle: false,
  is_aigc: false,
  tiktok_publish_id: 'v_pub_1',
  tiktok_post_ids: ['730000'],
  uploaded_bytes: 5_000_000,
  attempts: 1,
  fail_reason: null,
  fail_message: null,
  created_at: '2026-10-09T10:00:00Z',
  updated_at: '2026-10-09T10:05:00Z',
  started_at: '2026-10-09T10:00:05Z',
  finished_at: '2026-10-09T10:05:00Z',
}

export const detail = (over: Partial<PublicationDetail> = {}): PublicationDetail => ({
  ...publication,
  events: [
    { id: 'e1', created_at: '2026-10-09T10:00:00Z', type: 'created', from_status: null, to_status: 'QUEUED', message: 'Публикация поставлена в очередь', details: null },
    { id: 'e2', created_at: '2026-10-09T10:00:05Z', type: 'status_changed', from_status: 'QUEUED', to_status: 'UPLOADING', message: 'Видео загружается', details: null },
  ],
  media_filename: 'promo.mp4',
  media_size_bytes: 5_000_000,
  account_username: 'Test Creator',
  ...over,
})
