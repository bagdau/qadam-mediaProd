import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/services/api'
import { ApiError } from '@/services/http'
import { account, authUser, creator, detail, media, meta, publication, renderApp } from '@/test/utils'
import type { Dashboard } from '@/types/api'

vi.mock('@/services/api', () => ({
  authApi: { login: vi.fn(), register: vi.fn(), me: vi.fn(), logout: vi.fn(), changePassword: vi.fn(), sessions: vi.fn(), revokeSession: vi.fn() },
  accountsApi: { list: vi.fn(), startOAuth: vi.fn(), creatorInfo: vi.fn(), refresh: vi.fn(), disconnect: vi.fn() },
  mediaApi: { upload: vi.fn(), remove: vi.fn() },
  publicationsApi: { create: vi.fn(), list: vi.fn(), get: vi.fn(), cancel: vi.fn(), retry: vi.fn() },
  miscApi: { meta: vi.fn(), dashboard: vi.fn(), auditLogs: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }))
vi.mock('@/utils/video', () => ({ readVideoDuration: vi.fn().mockResolvedValue(30) }))

import { toast } from 'sonner'

const m = <T extends (...args: never[]) => unknown>(fn: T) => vi.mocked(fn)

const dashboard: Dashboard = {
  accounts_total: 1,
  accounts_needing_attention: 0,
  publications_total: 3,
  publications_by_status: { PUBLISHED: 2, PROCESSING: 1 },
  in_progress: 1,
  published_last_7_days: 2,
  daily: [{ date: '2026-10-08', total: 3, published: 2 }],
  recent: [{ id: 'p1', title: 'Launch day', status: 'PUBLISHED', created_at: '2026-10-09T10:00:00Z', privacy_level: 'SELF_ONLY' }],
}

function signedIn() {
  m(api.authApi.me).mockResolvedValue(authUser)
  m(api.miscApi.meta).mockResolvedValue(meta)
  m(api.accountsApi.list).mockResolvedValue([account])
  m(api.accountsApi.creatorInfo).mockResolvedValue(creator)
  m(api.miscApi.dashboard).mockResolvedValue(dashboard)
}

beforeEach(() => {
  vi.clearAllMocks()
  m(api.authApi.me).mockRejectedValue(new ApiError(401, 'unauthorized', 'Требуется вход'))
})

describe('authentication', () => {
  it('redirects anonymous users to login and remembers the target', async () => {
    const { router } = renderApp('/accounts')
    await screen.findByRole('heading', { name: 'Вход' })
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toBe('?next=%2Faccounts')
  })

  it('validates the login form before calling the API', async () => {
    const user = userEvent.setup()
    renderApp('/login')
    await user.click(await screen.findByRole('button', { name: 'Войти' }))
    expect(await screen.findByText('Введите адрес почты')).toBeInTheDocument()
    expect(screen.getByText('Введите пароль')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Адрес почты'), 'not-an-email')
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByText('Некорректный адрес почты')).toBeInTheDocument()
    expect(api.authApi.login).not.toHaveBeenCalled()
  })

  it('signs in and returns to the originally requested page', async () => {
    const user = userEvent.setup()
    m(api.authApi.login).mockResolvedValue(authUser)
    m(api.accountsApi.list).mockResolvedValue([account])
    m(api.miscApi.meta).mockResolvedValue(meta)
    const { router } = renderApp('/login?next=%2Faccounts')
    await user.type(await screen.findByLabelText('Адрес почты'), 'owner@example.com')
    await user.type(screen.getByLabelText('Пароль'), 'Correct-Horse-Battery-9')
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/accounts'))
    expect(api.authApi.login).toHaveBeenCalledWith('owner@example.com', 'Correct-Horse-Battery-9')
    expect(await screen.findByText('Test Creator')).toBeInTheDocument()
  })

  it('never redirects to an external site from ?next', async () => {
    const user = userEvent.setup()
    m(api.authApi.login).mockResolvedValue(authUser)
    m(api.miscApi.dashboard).mockResolvedValue(dashboard)
    m(api.miscApi.meta).mockResolvedValue(meta)
    const { router } = renderApp('/login?next=https%3A%2F%2Fevil.example')
    await user.type(await screen.findByLabelText('Адрес почты'), 'owner@example.com')
    await user.type(screen.getByLabelText('Пароль'), 'x')
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })

  it('shows the server error for wrong credentials', async () => {
    const user = userEvent.setup()
    m(api.authApi.login).mockRejectedValue(new ApiError(401, 'unauthorized', 'Неверный адрес почты или пароль'))
    renderApp('/login')
    await user.type(await screen.findByLabelText('Адрес почты'), 'owner@example.com')
    await user.type(screen.getByLabelText('Пароль'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный адрес почты или пароль')
    expect(toast.error).toHaveBeenCalled()
  })

  it('serves legal pages without authentication', async () => {
    renderApp('/privacy')
    expect(await screen.findByRole('heading', { name: 'Политика конфиденциальности' })).toBeInTheDocument()
    expect(screen.getByText(/Токены TikTok хранятся на сервере в зашифрованном виде/)).toBeInTheDocument()
  })
})

describe('dashboard', () => {
  it('shows skeleton, then numbers and the un-audited notice', async () => {
    signedIn()
    renderApp('/')
    expect(await screen.findByRole('status', { name: 'Загрузка обзора' })).toBeInTheDocument()
    expect(await screen.findByText('Опубликовано за 7 дней')).toBeInTheDocument()
    expect(screen.getByText('Приложение TikTok не прошло аудит')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Публикации за 7 дней/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Launch day/ })).toHaveAttribute('href', '/publications/p1')
  })

  it('offers a retry when loading fails', async () => {
    signedIn()
    m(api.miscApi.dashboard).mockRejectedValueOnce(new ApiError(500, 'internal_error', 'Ошибка сервера. Попробуйте позже.'))
    const user = userEvent.setup()
    renderApp('/')
    expect(await screen.findByRole('alert')).toHaveTextContent('Ошибка сервера')
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('Всего публикаций')).toBeInTheDocument()
  })

  it('prompts to connect an account when there are none', async () => {
    signedIn()
    m(api.miscApi.dashboard).mockResolvedValue({ ...dashboard, accounts_total: 0, publications_total: 0, in_progress: 0, recent: [], daily: [] })
    renderApp('/')
    expect(await screen.findByText('Подключите первый аккаунт TikTok')).toBeInTheDocument()
  })
})

describe('accounts', () => {
  it('lists accounts and asks for confirmation before disconnecting', async () => {
    signedIn()
    m(api.accountsApi.disconnect).mockResolvedValue()
    const user = userEvent.setup()
    renderApp('/accounts')
    await screen.findByText('Test Creator')
    await user.click(screen.getByRole('button', { name: /Отключить/ }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/удалим сохранённые токены/)).toBeInTheDocument()
    expect(api.accountsApi.disconnect).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Отключить аккаунт' }))
    await waitFor(() => expect(api.accountsApi.disconnect).toHaveBeenCalledWith('a1'))
    expect(toast.success).toHaveBeenCalled()
  })

  it('cancelling the confirmation keeps the account', async () => {
    signedIn()
    const user = userEvent.setup()
    renderApp('/accounts')
    await screen.findByText('Test Creator')
    await user.click(screen.getByRole('button', { name: /Отключить/ }))
    await user.click(await screen.findByRole('button', { name: 'Отмена' }))
    expect(api.accountsApi.disconnect).not.toHaveBeenCalled()
  })

  it('starts the OAuth flow on the server and navigates to TikTok', async () => {
    signedIn()
    m(api.accountsApi.startOAuth).mockResolvedValue('https://www.tiktok.com/v2/auth/authorize/?client_key=k&state=s')
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const user = userEvent.setup()
    renderApp('/accounts')
    await user.click(await screen.findByRole('button', { name: /Подключить TikTok/ }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith(expect.stringContaining('tiktok.com/v2/auth/authorize')))
    vi.unstubAllGlobals()
  })

  it('explains OAuth failures from the callback redirect and cleans the URL', async () => {
    signedIn()
    const { router } = renderApp('/accounts?oauth_error=oauth_state_invalid')
    await screen.findByText('Test Creator')
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('устарела')))
    expect(router.state.location.search).toBe('')
  })

  it('confirms a successful connection', async () => {
    signedIn()
    renderApp('/accounts?connected=a1')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('TikTok-аккаунт подключён'))
  })

  it('warns when the integration is not configured and blocks connecting', async () => {
    signedIn()
    m(api.miscApi.meta).mockResolvedValue({ ...meta, tiktok_configured: false })
    renderApp('/accounts')
    expect(await screen.findByText('Интеграция TikTok не настроена')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Подключить TikTok/ })).toBeDisabled()
  })

  it('flags accounts that need re-authorisation', async () => {
    signedIn()
    m(api.accountsApi.list).mockResolvedValue([{ ...account, status: 'needs_reauth' }])
    renderApp('/accounts')
    expect(await screen.findByText('Нужно переподключить')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Обновить доступ/ })).not.toBeInTheDocument()
  })
})

describe('publishing form', () => {
  async function chooseOption(user: ReturnType<typeof userEvent.setup>, trigger: HTMLElement, name: RegExp | string) {
    await user.click(trigger)
    await user.click(await screen.findByRole('option', { name }))
  }

  async function openForm() {
    signedIn()
    m(api.mediaApi.upload).mockResolvedValue(media)
    const user = userEvent.setup()
    renderApp('/publish')
    await screen.findByText(/Публикация пойдёт в/)
    return user
  }

  it('starts empty: no privacy preselected, every toggle off, submit disabled', async () => {
    await openForm()
    expect(screen.getByRole('combobox', { name: /Кто может смотреть/ })).toHaveTextContent('Выберите вариант')
    for (const name of [/Разрешить комментарии/, /Разрешить Duet/, /Разрешить Stitch/, /Раскрыть коммерческий контент/]) {
      expect(screen.getByRole('switch', { name })).not.toBeChecked()
    }
    expect(screen.getByRole('button', { name: 'Опубликовать' })).toBeDisabled()
  })

  it('only offers SELF_ONLY while the app is un-audited', async () => {
    const user = await openForm()
    await user.click(screen.getByRole('combobox', { name: /Кто может смотреть/ }))
    expect(await screen.findByRole('option', { name: 'Только я' })).not.toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('option', { name: /^Все — Недоступно/ })).toHaveAttribute('aria-disabled', 'true')
  })

  it('rejects an unsupported file before uploading', async () => {
    await openForm()
    const user = userEvent.setup({ applyAccept: false }) // drag&drop bypasses the picker's accept filter
    const file = new File(['x'], 'malware.exe', { type: 'application/x-msdownload' })
    await user.upload(screen.getByLabelText('Файл видео'), file)
    expect(await screen.findByText('Поддерживаются только MP4, MOV и WebM')).toBeInTheDocument()
    expect(api.mediaApi.upload).not.toHaveBeenCalled()
  })

  it('walks through upload, choices, confirmation and creates the publication', async () => {
    const user = await openForm()
    m(api.publicationsApi.create).mockResolvedValue({ ...publication, id: 'p9', status: 'QUEUED' })
    m(api.publicationsApi.get).mockResolvedValue(detail({ id: 'p9', status: 'QUEUED' }))

    await user.upload(screen.getByLabelText('Файл видео'), new File(['video'], 'promo.mp4', { type: 'video/mp4' }))
    expect(await screen.findByText('promo.mp4')).toBeInTheDocument()
    expect(api.mediaApi.upload).toHaveBeenCalledWith(expect.any(File), 30, expect.any(Function), expect.anything())

    await user.type(screen.getByLabelText('Описание'), 'Hello #qadam')
    await chooseOption(user, screen.getByRole('combobox', { name: /Кто может смотреть/ }), 'Только я')
    await user.click(screen.getByRole('switch', { name: /Разрешить комментарии/ }))

    const submit = screen.getByRole('button', { name: 'Опубликовать' })
    expect(submit).toBeDisabled() // music confirmation still missing
    await user.click(screen.getByRole('checkbox', { name: /Music Usage Confirmation/ }))
    await waitFor(() => expect(submit).toBeEnabled())

    await user.click(submit)
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/@tester/)).toBeInTheDocument()
    expect(api.publicationsApi.create).not.toHaveBeenCalled() // nothing is sent before explicit confirmation
    await user.click(within(dialog).getByRole('button', { name: 'Да, отправить' }))

    await waitFor(() => expect(api.publicationsApi.create).toHaveBeenCalledTimes(1))
    const [payload, key] = m(api.publicationsApi.create).mock.calls[0] as unknown as [Record<string, unknown>, string]
    expect(payload).toMatchObject({
      account_id: 'a1', media_id: 'm1', title: 'Hello #qadam', privacy_level: 'SELF_ONLY',
      allow_comment: true, allow_duet: false, allow_stitch: false, music_usage_confirmed: true, mode: 'DIRECT_POST',
    })
    expect(key.length).toBeGreaterThanOrEqual(8)
    expect((await screen.findAllByText('В очереди')).length).toBeGreaterThan(0)
  })

  it('greys out interactions the creator disabled and explains why', async () => {
    signedIn()
    m(api.accountsApi.creatorInfo).mockResolvedValue({ ...creator, comment_disabled: true, duet_disabled: true })
    renderApp('/publish')
    await screen.findByText(/Публикация пойдёт в/)
    expect(screen.getByRole('switch', { name: /Разрешить комментарии/ })).toBeDisabled()
    expect(screen.getByRole('switch', { name: /Разрешить Duet/ })).toBeDisabled()
    expect(screen.getByRole('switch', { name: /Разрешить Stitch/ })).toBeEnabled()
    expect(screen.getAllByText(/Отключено в настройках/).length).toBeGreaterThan(0)
  })

  it('requires a brand choice once commercial content is disclosed', async () => {
    const user = await openForm()
    await user.click(screen.getByRole('switch', { name: /Раскрыть коммерческий контент/ }))
    expect(await screen.findByRole('checkbox', { name: /Ваш бренд/ })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Брендированный контент/ })).not.toBeChecked()
    expect(screen.getAllByText(/Укажите, что вы продвигаете/).length).toBeGreaterThan(0)
  })

  it('reports a duplicate rejection from the server without navigating away', async () => {
    const user = await openForm()
    m(api.publicationsApi.create).mockRejectedValue(new ApiError(409, 'duplicate_publication', 'duplicate'))
    await user.upload(screen.getByLabelText('Файл видео'), new File(['v'], 'promo.mp4', { type: 'video/mp4' }))
    await screen.findByText('promo.mp4')
    await chooseOption(user, screen.getByRole('combobox', { name: /Кто может смотреть/ }), 'Только я')
    await user.click(screen.getByRole('checkbox', { name: /Music Usage Confirmation/ }))
    const submit = screen.getByRole('button', { name: 'Опубликовать' })
    await waitFor(() => expect(submit).toBeEnabled())
    await user.click(submit)
    await user.click(await screen.findByRole('button', { name: 'Да, отправить' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('уже публиковалось')))
    expect(screen.getByRole('button', { name: 'Опубликовать' })).toBeInTheDocument()
  })

  it('asks to connect an account when none is active', async () => {
    signedIn()
    m(api.accountsApi.list).mockResolvedValue([])
    renderApp('/publish')
    expect(await screen.findByText('Нет подключённого аккаунта')).toBeInTheDocument()
  })
})

describe('history and detail', () => {
  it('lists publications with status badges and paginates server-side', async () => {
    signedIn()
    m(api.publicationsApi.list).mockResolvedValue({
      items: [publication, { ...publication, id: 'p2', status: 'FAILED', title: 'Broken', fail_message: 'Формат не поддерживается' }],
      total: 12, limit: 10, offset: 0,
    })
    const user = userEvent.setup()
    renderApp('/publications')
    expect((await screen.findAllByText('Launch day #qadam')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Опубликовано').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Формат не поддерживается').length).toBeGreaterThan(0)
    expect(screen.getByText(/1–10 из 12/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Следующая страница' }))
    await waitFor(() => expect(api.publicationsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10, limit: 10 })))
  })

  it('shows an empty state', async () => {
    signedIn()
    m(api.publicationsApi.list).mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 })
    renderApp('/publications')
    expect(await screen.findByText('Публикаций пока нет')).toBeInTheDocument()
  })

  it('shows the timeline and cancel action for a queued publication', async () => {
    signedIn()
    m(api.publicationsApi.get).mockResolvedValue(detail({ status: 'QUEUED', tiktok_post_ids: null }))
    m(api.publicationsApi.cancel).mockResolvedValue({ ...publication, status: 'CANCELLED' })
    const user = userEvent.setup()
    renderApp('/publications/p1')
    expect(await screen.findByRole('list', { name: 'Этапы публикации' })).toBeInTheDocument()
    expect(screen.getByText(/Публикация поставлена в очередь/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Отменить' }))
    await waitFor(() => expect(api.publicationsApi.cancel).toHaveBeenCalledWith('p1'))
  })

  it('explains a failure and retries', async () => {
    signedIn()
    m(api.publicationsApi.get).mockResolvedValue(detail({ status: 'FAILED', fail_message: 'Формат файла не поддерживается TikTok.' }))
    m(api.publicationsApi.retry).mockResolvedValue({ ...publication, status: 'QUEUED' })
    const user = userEvent.setup()
    renderApp('/publications/p1')
    expect(await screen.findByText('Формат файла не поддерживается TikTok.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Повторить/ }))
    await waitFor(() => expect(api.publicationsApi.retry).toHaveBeenCalledWith('p1', false))
  })

  it('requires explicit confirmation before retrying an uncertain publication', async () => {
    signedIn()
    m(api.publicationsApi.get).mockResolvedValue(detail({ status: 'NEEDS_REVIEW', fail_message: 'Результат запроса к TikTok неизвестен.' }))
    m(api.publicationsApi.retry)
      .mockRejectedValueOnce(new ApiError(409, 'duplicate_risk', 'risk'))
      .mockResolvedValueOnce({ ...publication, status: 'QUEUED' })
    const user = userEvent.setup()
    renderApp('/publications/p1')
    await user.click(await screen.findByRole('button', { name: /Повторить/ }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/Возможен дубль/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Видео нет — повторить' }))
    await waitFor(() => expect(api.publicationsApi.retry).toHaveBeenLastCalledWith('p1', true))
  })

  it('handles a missing publication', async () => {
    signedIn()
    m(api.publicationsApi.get).mockRejectedValue(new ApiError(404, 'not_found', 'Публикация не найдена'))
    renderApp('/publications/nope')
    expect(await screen.findByRole('alert')).toHaveTextContent('Публикация не найдена')
  })
})

describe('settings', () => {
  it('validates the new password and submits the change', async () => {
    signedIn()
    m(api.authApi.sessions).mockResolvedValue([])
    m(api.miscApi.auditLogs).mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 })
    m(api.authApi.changePassword).mockResolvedValue()
    const user = userEvent.setup()
    renderApp('/settings')
    await user.type(await screen.findByLabelText('Текущий пароль'), 'old-password-1')
    await user.type(screen.getByLabelText('Новый пароль'), 'short')
    await user.type(screen.getByLabelText('Повторите новый пароль'), 'different')
    await user.click(screen.getByRole('button', { name: 'Сменить пароль' }))
    expect(await screen.findByText('Не короче 12 символов')).toBeInTheDocument()
    expect(screen.getByText('Пароли не совпадают')).toBeInTheDocument()
    expect(api.authApi.changePassword).not.toHaveBeenCalled()

    await user.clear(screen.getByLabelText('Новый пароль'))
    await user.clear(screen.getByLabelText('Повторите новый пароль'))
    await user.type(screen.getByLabelText('Новый пароль'), 'A-Brand-New-Passw0rd')
    await user.type(screen.getByLabelText('Повторите новый пароль'), 'A-Brand-New-Passw0rd')
    await user.click(screen.getByRole('button', { name: 'Сменить пароль' }))
    await waitFor(() => expect(api.authApi.changePassword).toHaveBeenCalledWith('old-password-1', 'A-Brand-New-Passw0rd'))
  })

  it('lists sessions and can end another one', async () => {
    signedIn()
    m(api.authApi.sessions).mockResolvedValue([
      { id: 's1', created_at: '', last_seen_at: '2026-10-09T10:00:00Z', expires_at: '', ip_address: '10.0.0.1', user_agent: 'Chrome', current: true },
      { id: 's2', created_at: '', last_seen_at: '2026-10-08T10:00:00Z', expires_at: '', ip_address: '10.0.0.2', user_agent: 'Firefox', current: false },
    ])
    m(api.miscApi.auditLogs).mockResolvedValue({ items: [{ id: 'l1', created_at: '2026-10-09T10:00:00Z', action: 'auth.login', entity_type: null, entity_id: null, ip_address: null, details: null }], total: 1, limit: 10, offset: 0 })
    m(api.authApi.revokeSession).mockResolvedValue()
    const user = userEvent.setup()
    renderApp('/settings')
    expect(await screen.findByText('Это устройство')).toBeInTheDocument()
    expect(screen.getByText('Вход в систему')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Завершить' }))
    await waitFor(() => expect(api.authApi.revokeSession).toHaveBeenCalledWith('s2'))
  })
})

describe('theme', () => {
  it('switches to dark mode and persists the choice', async () => {
    signedIn()
    m(api.publicationsApi.list).mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 })
    m(api.authApi.sessions).mockResolvedValue([])
    m(api.miscApi.auditLogs).mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 })
    const user = userEvent.setup()
    renderApp('/settings')
    const radio = (await screen.findAllByRole('radio', { name: 'Тёмная' }))[0]
    await user.click(radio)
    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem('qm-theme')).toBe('dark')
    await user.click(screen.getAllByRole('radio', { name: 'Светлая' })[0])
    expect(document.documentElement).not.toHaveClass('dark')
  })
})

describe('logout', () => {
  it('returns to the login page and drops cached data', async () => {
    signedIn()
    m(api.authApi.logout).mockImplementation(async () => {
      m(api.authApi.me).mockRejectedValue(new ApiError(401, 'unauthorized', 'Требуется вход'))
    })
    const user = userEvent.setup()
    const { router, client } = renderApp('/')
    await screen.findByText('Опубликовано за 7 дней')
    await user.click(screen.getAllByRole('button', { name: /Выйти/ })[0])
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
    expect(client.getQueryData(['dashboard'])).toBeUndefined()
  })
})
