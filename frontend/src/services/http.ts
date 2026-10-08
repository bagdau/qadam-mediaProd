import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'

/** Normalised error thrown by every API call. `message` is safe to show to the user. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown
  readonly retryAfter?: number

  constructor(status: number, code: string, message: string, details?: unknown, retryAfter?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.retryAfter = retryAfter
  }
}

const CSRF_COOKIE = 'qm_csrf'
const UNSAFE = new Set(['post', 'put', 'patch', 'delete'])
let memoryCsrf: string | null = null

export function setCsrfToken(token: string | null) {
  memoryCsrf = token
}

function readCsrf(): string | null {
  const match = document.cookie.split('; ').find((c) => c.startsWith(`${CSRF_COOKIE}=`))
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : memoryCsrf
}

export const http = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  timeout: 30_000,
  headers: { Accept: 'application/json' },
})

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (UNSAFE.has((config.method ?? 'get').toLowerCase())) {
    const token = readCsrf()
    if (token) config.headers.set('X-CSRF-Token', token)
  }
  return config
})

type ErrorBody = { error?: { code?: string; message?: string; details?: unknown } }

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isCancel(error)) throw error
    const err = error as AxiosError<ErrorBody>
    if (!err.response) {
      throw new ApiError(0, 'network_error', 'Нет связи с сервером. Проверьте подключение и повторите попытку.')
    }
    const { status, data, headers, config } = err.response
    const body = data?.error
    const retryAfter = Number(headers?.['retry-after']) || undefined
    const message =
      body?.message ??
      (status >= 500 ? 'Ошибка сервера. Попробуйте позже.' : `Не удалось выполнить запрос (HTTP ${status})`)
    const isAuthEndpoint = config?.url?.startsWith('/auth/login') || config?.url === '/auth/me'
    if (status === 401 && !isAuthEndpoint) onUnauthorized?.()
    throw new ApiError(status, body?.code ?? `http_${status}`, message, body?.details, retryAfter)
  },
)

export function errorMessage(error: unknown, fallback = 'Что-то пошло не так'): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : fallback
}
