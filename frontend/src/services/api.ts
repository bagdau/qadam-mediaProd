import { http, setCsrfToken } from '@/services/http'
import type {
  Account,
  AuditLogEntry,
  AuthResponse,
  CreatorInfo,
  Dashboard,
  MediaAsset,
  Meta,
  Page,
  Publication,
  PublicationCreate,
  PublicationDetail,
  PublicationStatus,
  SessionInfo,
} from '@/types/api'

export const authApi = {
  async login(email: string, password: string) {
    const { data } = await http.post<AuthResponse>('/auth/login', { email, password })
    setCsrfToken(data.csrf_token)
    return data
  },
  async register(email: string, password: string, display_name: string) {
    const { data } = await http.post<AuthResponse>('/auth/register', { email, password, display_name })
    setCsrfToken(data.csrf_token)
    return data
  },
  async me() {
    const { data } = await http.get<AuthResponse>('/auth/me')
    setCsrfToken(data.csrf_token)
    return data
  },
  async logout() {
    await http.post('/auth/logout')
    setCsrfToken(null)
  },
  async changePassword(current_password: string, new_password: string) {
    await http.post('/auth/password', { current_password, new_password })
  },
  async sessions() {
    return (await http.get<SessionInfo[]>('/auth/sessions')).data
  },
  async revokeSession(id: string) {
    await http.delete(`/auth/sessions/${id}`)
  },
}

export const accountsApi = {
  async list() {
    return (await http.get<Account[]>('/accounts')).data
  },
  async startOAuth() {
    return (await http.post<{ authorization_url: string }>('/tiktok/oauth/start')).data.authorization_url
  },
  async creatorInfo(id: string) {
    return (await http.get<CreatorInfo>(`/accounts/${id}/creator-info`)).data
  },
  async refresh(id: string) {
    return (await http.post<Account>(`/accounts/${id}/refresh`)).data
  },
  async disconnect(id: string) {
    await http.delete(`/accounts/${id}`)
  },
}

export const mediaApi = {
  async upload(file: File, durationSeconds: number | null, onProgress?: (percent: number) => void, signal?: AbortSignal) {
    const form = new FormData()
    form.append('video', file)
    if (durationSeconds != null) form.append('duration_seconds', String(durationSeconds))
    const { data } = await http.post<MediaAsset>('/media', form, {
      timeout: 0,
      signal,
      onUploadProgress: (e) => {
        if (e.total) onProgress?.(Math.round((e.loaded / e.total) * 100))
      },
    })
    return data
  },
  async remove(id: string) {
    await http.delete(`/media/${id}`)
  },
}

export const publicationsApi = {
  async create(payload: PublicationCreate, idempotencyKey: string) {
    return (await http.post<Publication>('/publications', payload, { headers: { 'Idempotency-Key': idempotencyKey } })).data
  },
  async list(params: { status?: PublicationStatus; limit?: number; offset?: number }) {
    return (await http.get<Page<Publication>>('/publications', { params })).data
  },
  async get(id: string) {
    return (await http.get<PublicationDetail>(`/publications/${id}`)).data
  },
  async cancel(id: string) {
    return (await http.post<Publication>(`/publications/${id}/cancel`)).data
  },
  async retry(id: string, confirmDuplicateRisk = false) {
    return (await http.post<Publication>(`/publications/${id}/retry`, { confirm_duplicate_risk: confirmDuplicateRisk })).data
  },
}

export const miscApi = {
  async meta() {
    return (await http.get<Meta>('/meta')).data
  },
  async dashboard() {
    return (await http.get<Dashboard>('/dashboard')).data
  },
  async auditLogs(params: { limit?: number; offset?: number }) {
    return (await http.get<Page<AuditLogEntry>>('/audit-logs', { params })).data
  },
}
