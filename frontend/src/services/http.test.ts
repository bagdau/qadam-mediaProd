import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, errorMessage, http, setCsrfToken, setUnauthorizedHandler } from './http'

type Reply = { status: number; data?: unknown; headers?: Record<string, string> }

function respondWith(reply: Reply | Error, capture?: (c: InternalAxiosRequestConfig) => void) {
  const adapter: AxiosAdapter = async (config) => {
    capture?.(config)
    if (reply instanceof Error) throw new AxiosError(reply.message, 'ERR_NETWORK', config)
    const response = { data: reply.data ?? {}, status: reply.status, statusText: '', headers: reply.headers ?? {}, config }
    if (reply.status >= 400) throw new AxiosError('failed', 'ERR_BAD_REQUEST', config, null, response)
    return response
  }
  http.defaults.adapter = adapter
}

describe('http client', () => {
  beforeEach(() => {
    setCsrfToken(null)
    document.cookie = 'qm_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  })
  afterEach(() => setUnauthorizedHandler(null))

  it('uses cookies and the versioned base path', () => {
    expect(http.defaults.withCredentials).toBe(true)
    expect(http.defaults.baseURL).toBe('/api/v1')
  })

  it('sends the CSRF token on state-changing requests only', async () => {
    document.cookie = 'qm_csrf=token-from-cookie; path=/'
    let seen: InternalAxiosRequestConfig | undefined
    respondWith({ status: 200 }, (c) => (seen = c))
    await http.post('/x', {})
    expect(seen?.headers.get('X-CSRF-Token')).toBe('token-from-cookie')
    await http.delete('/x')
    expect(seen?.headers.get('X-CSRF-Token')).toBe('token-from-cookie')
    await http.get('/x')
    expect(seen?.headers.get('X-CSRF-Token')).toBeFalsy()
  })

  it('falls back to the in-memory token when the cookie is unavailable', async () => {
    setCsrfToken('memory-token')
    let seen: InternalAxiosRequestConfig | undefined
    respondWith({ status: 200 }, (c) => (seen = c))
    await http.post('/x', {})
    expect(seen?.headers.get('X-CSRF-Token')).toBe('memory-token')
  })

  it('normalises API errors', async () => {
    respondWith({ status: 409, data: { error: { code: 'duplicate_publication', message: 'Уже публиковалось', details: { id: 1 } } } })
    const error = await http.get('/x').catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, code: 'duplicate_publication', message: 'Уже публиковалось', details: { id: 1 } })
  })

  it('reads Retry-After on rate limiting', async () => {
    respondWith({ status: 429, data: { error: { code: 'rate_limited', message: 'Слишком много' } }, headers: { 'retry-after': '42' } })
    const error = (await http.get('/x').catch((e) => e)) as ApiError
    expect(error.retryAfter).toBe(42)
  })

  it('gives a friendly message for network failures and 5xx without a body', async () => {
    respondWith(new Error('boom'))
    expect(((await http.get('/x').catch((e) => e)) as ApiError).code).toBe('network_error')
    respondWith({ status: 502, data: '<html>bad gateway</html>' })
    const error = (await http.get('/x').catch((e) => e)) as ApiError
    expect(error.message).toBe('Ошибка сервера. Попробуйте позже.')
    expect(error.message).not.toContain('html')
  })

  it('notifies on 401 except for login and the session probe', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    respondWith({ status: 401, data: { error: { code: 'unauthorized', message: 'no' } } })
    await http.get('/publications').catch(() => undefined)
    expect(handler).toHaveBeenCalledTimes(1)
    await http.post('/auth/login', {}).catch(() => undefined)
    await http.get('/auth/me').catch(() => undefined)
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('extracts messages safely', () => {
    expect(errorMessage(new ApiError(400, 'x', 'понятно'))).toBe('понятно')
    expect(errorMessage(new Error('plain'))).toBe('plain')
    expect(errorMessage('weird', 'запасной')).toBe('запасной')
  })
})
