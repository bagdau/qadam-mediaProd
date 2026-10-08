import { expect, test } from '@playwright/test'
import { fakeMp4 } from './helpers'

/**
 * Full-stack journey: React -> nginx -> FastAPI -> Postgres/Redis -> Celery worker -> mock TikTok.
 * Needs `docker compose --profile mock up` configured with the mock TikTok endpoints (see README, "Local TikTok mock").
 *   E2E_STACK=1 E2E_EMAIL=... E2E_PASSWORD=... npx playwright test --project=desktop
 */
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? ''

test.skip(!process.env.E2E_STACK, 'set E2E_STACK=1 with a running docker compose stack')

test('sign in, connect TikTok (mock), upload, publish and watch it complete', async ({ page }) => {
  test.skip(!password, 'E2E_PASSWORD is required')

  await page.goto('/login')
  await page.getByLabel('Адрес почты').fill(email)
  await page.getByLabel('Пароль').fill(password)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('heading', { name: 'Обзор' })).toBeVisible()

  await page.goto('/accounts')
  if (!(await page.getByText('Mock Creator').isVisible({ timeout: 3000 }).catch(() => false))) {
    await page.getByRole('button', { name: /Подключить TikTok/ }).click()
    await page.getByRole('button', { name: 'Разрешить' }).click() // mock TikTok consent page
    await expect(page.getByText('Mock Creator')).toBeVisible()
  }
  await expect(page.getByText('Подключён', { exact: true }).first()).toBeVisible()

  await page.goto('/publish')
  await expect(page.getByText('Публикация пойдёт в')).toBeVisible()
  await page.getByLabel('Файл видео').setInputFiles({ name: 'e2e.mp4', mimeType: 'video/mp4', buffer: fakeMp4(8, 20_000) })
  await expect(page.getByText('e2e.mp4')).toBeVisible()
  await page.getByLabel('Описание').fill(`Full-stack E2E ${Date.now()} #qadam`)
  await page.getByRole('combobox', { name: /Кто может смотреть/ }).click()
  await page.getByRole('option', { name: 'Только я' }).click()
  await page.getByRole('checkbox', { name: /Music Usage Confirmation/ }).click()
  await page.getByRole('button', { name: 'Опубликовать' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Да, отправить' }).click()

  await expect(page).toHaveURL(/\/publications\/[0-9a-f-]{36}$/)
  // The worker uploads, then polls with backoff; the mock completes ~8 s after the upload.
  await expect(page.getByText('TikTok подтвердил публикацию.')).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('Опубликовано', { exact: true }).first()).toBeVisible()
})
