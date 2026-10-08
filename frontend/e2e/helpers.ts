import type { Page, Route } from '@playwright/test'

/** Smallest byte sequence the backend accepts as an MP4 (ftyp + moov/mvhd + mdat). */
export function fakeMp4(durationSeconds = 12, payload = 4096): Buffer {
  const u32 = (n: number) => {
    const b = Buffer.alloc(4)
    b.writeUInt32BE(n)
    return b
  }
  const box = (type: string, body: Buffer) => Buffer.concat([u32(body.length + 8), Buffer.from(type), body])
  const ftyp = box('ftyp', Buffer.concat([Buffer.from('isom'), u32(512), Buffer.from('isomiso2mp41')]))
  const mvhd = box('mvhd', Buffer.concat([u32(0), u32(0), u32(0), u32(1000), u32(durationSeconds * 1000), Buffer.alloc(80)]))
  const moov = box('moov', mvhd)
  const random = Buffer.from(Array.from({ length: payload }, () => Math.floor(Math.random() * 256)))
  return Buffer.concat([ftyp, moov, box('mdat', random)])
}

const now = new Date().toISOString()
export const user = { id: 'u1', email: 'owner@example.com', display_name: 'Owner', role: 'member', created_at: now, last_login_at: now }

export const account = {
  id: 'a1', provider: 'tiktok', provider_account_id: 'open-1', username: 'tester', display_name: 'Test Creator', avatar_url: null,
  scopes: ['user.info.basic', 'video.publish', 'video.upload'], status: 'active', last_error: null, connected_at: now,
  access_expires_at: new Date(Date.now() + 864e5).toISOString(), refresh_expires_at: new Date(Date.now() + 365 * 864e5).toISOString(),
  last_refreshed_at: null, disconnected_at: null,
}

export const creator = {
  username: 'tester', nickname: 'Test Creator', avatar_url: null,
  privacy_level_options: ['PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY'],
  comment_disabled: false, duet_disabled: false, stitch_disabled: false, max_video_post_duration_sec: 600,
}

export interface MockState {
  loggedIn: boolean
  accounts: unknown[]
  publicationPolls: number
  createdBody?: Record<string, unknown>
  createdKey?: string
  dashboardFails: number
}

const meta = { tiktok_configured: true, tiktok_client_audited: false, scopes: ['user.info.basic', 'video.publish'], max_video_mb: 512,
  allowed_content_types: ['video/mp4', 'video/quicktime', 'video/webm'], allow_registration: false }

function publication(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: 'p-new', account_id: 'a1', media_id: 'm1', mode: 'DIRECT_POST', status, title: 'E2E post', privacy_level: 'SELF_ONLY',
    disable_comment: true, disable_duet: true, disable_stitch: true, brand_content_toggle: false, brand_organic_toggle: false, is_aigc: false,
    tiktok_publish_id: 'v_pub_1', tiktok_post_ids: status === 'PUBLISHED' ? ['730000'] : null, uploaded_bytes: 5000, attempts: 1,
    fail_reason: null, fail_message: null, created_at: now, updated_at: now, started_at: now, finished_at: null, ...extra,
  }
}

/** Network-level fake of the backend API (the real stack is covered by e2e/stack.spec.ts). */
export async function mockApi(page: Page, state: MockState) {
  const json = (route: Route, status: number, body: unknown, headers: Record<string, string> = {}) =>
    route.fulfill({ status, contentType: 'application/json', headers, body: JSON.stringify(body) })
  const err = (route: Route, status: number, code: string, message: string) => json(route, status, { error: { code, message } })

  await page.route('**/api/v1/**', async (route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname.replace('/api/v1', '')
    const method = req.method()
    const authed = state.loggedIn

    if (path === '/auth/login' && method === 'POST') {
      const body = req.postDataJSON() as { password: string }
      if (body.password !== 'Correct-Horse-Battery-9') return err(route, 401, 'unauthorized', 'Неверный адрес почты или пароль')
      state.loggedIn = true
      return json(route, 200, { user, csrf_token: 'csrf' })
    }
    if (path === '/auth/me') return authed ? json(route, 200, { user, csrf_token: 'csrf' }) : err(route, 401, 'unauthorized', 'Требуется вход')
    if (path === '/auth/logout') {
      state.loggedIn = false
      return route.fulfill({ status: 204 })
    }
    if (path === '/meta') return json(route, 200, meta)
    if (!authed) return err(route, 401, 'unauthorized', 'Требуется вход')

    if (path === '/dashboard') {
      if (state.dashboardFails > 0) {
        state.dashboardFails--
        return err(route, 500, 'internal_error', 'Ошибка сервера. Попробуйте позже.')
      }
      return json(route, 200, {
        accounts_total: state.accounts.length, accounts_needing_attention: 0, publications_total: 0, publications_by_status: {},
        in_progress: 0, published_last_7_days: 0, daily: [], recent: [],
      })
    }
    if (path === '/accounts') return json(route, 200, state.accounts)
    if (path === '/accounts/a1/creator-info') return json(route, 200, creator)
    if (path === '/media' && method === 'POST') {
      return json(route, 201, { id: 'm1', original_filename: 'promo.mp4', content_type: 'video/mp4', size_bytes: 5000, duration_seconds: 12,
        sha256: 'a'.repeat(64), status: 'ready', created_at: now })
    }
    if (path === '/media/m1' && method === 'DELETE') return route.fulfill({ status: 204 })
    if (path === '/publications' && method === 'POST') {
      state.createdBody = req.postDataJSON()
      state.createdKey = req.headers()['idempotency-key']
      return json(route, 201, publication('QUEUED'))
    }
    if (path === '/publications') return json(route, 200, { items: [], total: 0, limit: 10, offset: 0 })
    if (path === '/publications/p-new') {
      state.publicationPolls++
      const status = state.publicationPolls < 2 ? 'QUEUED' : state.publicationPolls < 3 ? 'PROCESSING' : 'PUBLISHED'
      return json(route, 200, {
        ...publication(status, { finished_at: status === 'PUBLISHED' ? now : null }),
        events: [{ id: 'e1', created_at: now, type: 'created', from_status: null, to_status: 'QUEUED', message: 'Публикация поставлена в очередь', details: null }],
        media_filename: 'promo.mp4', media_size_bytes: 5000, account_username: 'Test Creator',
      })
    }
    if (path === '/auth/sessions') return json(route, 200, [])
    if (path === '/audit-logs') return json(route, 200, { items: [], total: 0, limit: 10, offset: 0 })
    return err(route, 404, 'not_found', `unmocked ${method} ${path}`)
  })
}
