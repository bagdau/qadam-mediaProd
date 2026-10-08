import { defineConfig, devices } from '@playwright/test'

// E2E_STACK=1  -> run e2e/stack.spec.ts against a running `docker compose` stack (E2E_BASE_URL, default http://localhost:8080)
// default      -> run e2e/app.spec.ts against the production bundle (vite preview) with the API mocked at the network layer
const stack = !!process.env.E2E_STACK

export default defineConfig({
  testDir: './e2e',
  testMatch: stack ? /stack\.spec\.ts/ : /app\.spec\.ts/,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? (stack ? 'http://localhost:8080' : 'http://127.0.0.1:4173'),
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'ru-RU',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: stack
    ? undefined
    : { command: 'npm run build && npm run preview', url: 'http://127.0.0.1:4173', reuseExistingServer: true, timeout: 180_000 },
})
