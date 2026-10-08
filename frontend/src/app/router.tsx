import type * as React from 'react'
import { createBrowserRouter, createMemoryRouter, Link, type RouteObject } from 'react-router-dom'
import { RequireAuth } from '@/app/layout'
import { LoginPage } from '@/features/auth/login-page'

function NotFound() {
  return (
    <div className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="text-5xl font-semibold text-primary">404</p>
      <h1 className="text-xl font-semibold">Страница не найдена</h1>
      <p className="text-sm text-muted-foreground">Возможно, ссылка устарела или адрес введён с ошибкой.</p>
      <Link className="text-sm font-medium text-primary underline-offset-4 hover:underline" to="/">На главную</Link>
    </div>
  )
}

// Pages are code-split: only the login screen and shell are in the initial bundle.
const page = <T extends string>(load: () => Promise<Record<T, React.ComponentType>>, name: T) => async () => ({
  Component: (await load())[name],
})

export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  { path: '/terms', lazy: page(() => import('@/features/legal/legal-pages'), 'TermsPage') },
  { path: '/privacy', lazy: page(() => import('@/features/legal/legal-pages'), 'PrivacyPage') },
  {
    element: <RequireAuth />,
    children: [
      { index: true, lazy: page(() => import('@/features/dashboard/dashboard-page'), 'DashboardPage') },
      { path: 'accounts', lazy: page(() => import('@/features/tiktok/accounts-page'), 'AccountsPage') },
      { path: 'publish', lazy: page(() => import('@/features/publishing/publish-page'), 'PublishPage') },
      { path: 'publications', lazy: page(() => import('@/features/publishing/publications-page'), 'PublicationsPage') },
      { path: 'publications/:id', lazy: page(() => import('@/features/publishing/publication-detail-page'), 'PublicationDetailPage') },
      { path: 'settings', lazy: page(() => import('@/features/settings/settings-page'), 'SettingsPage') },
      { path: '*', element: <NotFound /> },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)
export const createTestRouter = (initialEntries: string[]) => createMemoryRouter(routes, { initialEntries })
