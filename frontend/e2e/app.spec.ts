import { expect, test, type Page } from '@playwright/test'
import { account, fakeMp4, mockApi, type MockState } from './helpers'

const fresh = (over: Partial<MockState> = {}): MockState => ({
  loggedIn: false, accounts: [account], publicationPolls: 0, dashboardFails: 0, ...over,
})

/** Below Tailwind's `lg` breakpoint the sidebar is a drawer. Decide by viewport (not by visibility) so we wait for the shell. */
async function openMenuIfMobile(page: Page) {
  const width = page.viewportSize()?.width ?? 1280
  if (width < 1024) await page.getByRole('button', { name: 'Открыть меню' }).click()
}

test.describe('authentication', () => {
  test('guards private pages, rejects bad credentials, then returns to the requested page', async ({ page }) => {
    await mockApi(page, fresh())
    await page.goto('/accounts')
    await expect(page).toHaveURL(/\/login\?next=%2Faccounts/)

    await page.getByLabel('Адрес почты').fill('owner@example.com')
    await page.getByLabel('Пароль').fill('wrong-password')
    await page.getByRole('button', { name: 'Войти' }).click()
    await expect(page.getByRole('alert').first()).toContainText('Неверный адрес почты или пароль')

    await page.getByLabel('Пароль').fill('Correct-Horse-Battery-9')
    await page.getByRole('button', { name: 'Войти' }).click()
    await expect(page).toHaveURL(/\/accounts$/)
    await expect(page.getByText('Test Creator')).toBeVisible()
  })

  test('legal pages are public', async ({ page }) => {
    await mockApi(page, fresh())
    for (const [path, heading] of [['/terms', 'Условия использования'], ['/privacy', 'Политика конфиденциальности']] as const) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    }
  })

  test('shows validation before any request is sent', async ({ page }) => {
    await mockApi(page, fresh())
    await page.goto('/login')
    await page.getByRole('button', { name: 'Войти' }).click()
    await expect(page.getByText('Введите адрес почты')).toBeVisible()
    await expect(page.getByText('Введите пароль')).toBeVisible()
  })
})

test.describe('publishing', () => {
  test('uploads a video, requires explicit choices, confirms, and follows the status to PUBLISHED', async ({ page }) => {
    const state = fresh({ loggedIn: true })
    await mockApi(page, state)
    await page.goto('/publish')
    await expect(page.getByText('Публикация пойдёт в')).toBeVisible()

    const submit = page.getByRole('button', { name: 'Опубликовать' })
    await expect(submit).toBeDisabled()
    await expect(page.getByRole('combobox', { name: /Кто может смотреть/ })).toContainText('Выберите вариант')

    await page.getByLabel('Файл видео').setInputFiles({ name: 'promo.mp4', mimeType: 'video/mp4', buffer: fakeMp4() })
    await expect(page.getByText('promo.mp4')).toBeVisible()

    await page.getByLabel('Описание').fill('E2E post #qadam')
    await page.getByRole('combobox', { name: /Кто может смотреть/ }).click()
    await expect(page.getByRole('option', { name: /^Все — Недоступно/ })).toHaveAttribute('aria-disabled', 'true')
    await page.getByRole('option', { name: 'Только я' }).click()
    await expect(submit).toBeDisabled() // music usage confirmation still unchecked
    await page.getByRole('checkbox', { name: /Music Usage Confirmation/ }).click()
    await expect(submit).toBeEnabled()

    await submit.click()
    const dialog = page.getByRole('alertdialog')
    await expect(dialog).toContainText('@tester')
    expect(state.createdBody).toBeUndefined() // nothing was sent before confirmation
    await dialog.getByRole('button', { name: 'Да, отправить' }).click()

    await expect(page).toHaveURL(/\/publications\/p-new$/)
    expect(state.createdBody).toMatchObject({ privacy_level: 'SELF_ONLY', allow_comment: false, allow_duet: false, allow_stitch: false,
      music_usage_confirmed: true, title: 'E2E post #qadam' })
    expect(state.createdKey).toBeTruthy()
    await expect(page.getByText('TikTok подтвердил публикацию.')).toBeVisible({ timeout: 20_000 }) // polling advanced QUEUED -> PUBLISHED
  })

  test('rejects an unsupported file locally', async ({ page }) => {
    await mockApi(page, fresh({ loggedIn: true }))
    await page.goto('/publish')
    await page.getByLabel('Файл видео').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('hello') })
    await expect(page.getByRole('alert').filter({ hasText: 'Поддерживаются только MP4, MOV и WebM' })).toBeVisible()
  })

  test('asks to connect an account first when none exists', async ({ page }) => {
    await mockApi(page, fresh({ loggedIn: true, accounts: [] }))
    await page.goto('/publish')
    await expect(page.getByText('Нет подключённого аккаунта')).toBeVisible()
    await page.getByRole('link', { name: 'Перейти к аккаунтам' }).click()
    await expect(page).toHaveURL(/\/accounts$/)
  })
})

test.describe('resilience and UX', () => {
  test('recovers from a server error with the retry button', async ({ page }) => {
    await mockApi(page, fresh({ loggedIn: true, dashboardFails: 3 }))
    await page.goto('/')
    await expect(page.getByRole('alert')).toContainText('Ошибка сервера')
    await page.getByRole('button', { name: 'Повторить' }).click()
    await expect(page.getByText('Подключённые аккаунты')).toBeVisible()
  })

  test('theme choice survives a reload and is applied before first paint', async ({ page }) => {
    await mockApi(page, fresh({ loggedIn: true }))
    await page.goto('/settings')
    await page.getByRole('radio', { name: 'Тёмная' }).first().click()
    await expect(page.locator('html')).toHaveClass(/dark/)
    await page.reload()
    await expect(page.locator('html')).toHaveClass(/dark/)
    await page.getByRole('radio', { name: 'Светлая' }).first().click()
    await expect(page.locator('html')).not.toHaveClass(/dark/)
  })

  test('navigation works on every screen size and the page never scrolls sideways', async ({ page }) => {
    await mockApi(page, fresh({ loggedIn: true }))
    await page.goto('/')
    for (const [name, url] of [['Аккаунты TikTok', /\/accounts$/], ['Новая публикация', /\/publish$/], ['История', /\/publications$/], ['Настройки', /\/settings$/]] as const) {
      await openMenuIfMobile(page)
      await page.getByRole('navigation', { name: 'Основная навигация' }).getByRole('link', { name }).click()
      await expect(page).toHaveURL(url)
      await expect(page.getByRole('dialog')).toHaveCount(0) // the drawer finished closing (mobile)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow).toBeLessThanOrEqual(1)
    }
  })

  test('keyboard users can skip to the content', async ({ page }) => {
    await mockApi(page, fresh({ loggedIn: true }))
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Обзор' })).toBeVisible() // wait until the shell has rendered
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'Перейти к содержимому' })).toBeFocused()
  })

  test('logout returns to the login page', async ({ page }) => {
    await mockApi(page, fresh({ loggedIn: true }))
    await page.goto('/')
    await openMenuIfMobile(page)
    await page.getByRole('button', { name: 'Выйти' }).click()
    await expect(page).toHaveURL(/\/login/)
  })
})
