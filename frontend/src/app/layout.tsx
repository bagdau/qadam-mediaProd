import { BarChart3, History, LayoutDashboard, LogOut, Menu, Send, Settings, Users } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { ThemeToggle } from '@/components/shared/theme-toggle'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth, useLogout } from '@/hooks/use-auth'
import { cn } from '@/utils/cn'

export function Logo({ className }: { className?: string }) {
  return (
    <Link to="/" className={cn('flex items-center gap-2.5 font-semibold tracking-tight', className)} aria-label="Qadam Media — на главную">
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <BarChart3 className="size-4.5" aria-hidden />
      </span>
      <span>Qadam Media</span>
    </Link>
  )
}

const NAV = [
  { to: '/', label: 'Обзор', icon: LayoutDashboard, end: true },
  { to: '/accounts', label: 'Аккаунты TikTok', icon: Users },
  { to: '/publish', label: 'Новая публикация', icon: Send },
  { to: '/publications', label: 'История', icon: History },
  { to: '/settings', label: 'Настройки', icon: Settings },
]

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Основная навигация" className="flex flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground',
              isActive && 'bg-accent text-accent-foreground',
            )
          }
        >
          <Icon className="size-4" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

function UserBlock() {
  const { user } = useAuth()
  const logout = useLogout()
  return (
    <div className="space-y-3">
      <div className="min-w-0 px-1">
        <p className="truncate text-sm font-medium">{user?.display_name || user?.email}</p>
        {user?.display_name && <p className="truncate text-xs text-muted-foreground">{user.email}</p>}
      </div>
      <div className="flex items-center justify-between gap-2">
        <ThemeToggle />
        <Button variant="ghost" size="sm" onClick={() => logout.mutate()} loading={logout.isPending}>
          <LogOut aria-hidden /> Выйти
        </Button>
      </div>
    </div>
  )
}

export function AppShell() {
  const [open, setOpen] = useState(false)
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[60] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground">
        Перейти к содержимому
      </a>
      <aside className="sticky top-0 hidden h-dvh flex-col justify-between border-r bg-sidebar p-4 lg:flex">
        <div className="space-y-6">
          <Logo className="px-2 pt-1" />
          <NavLinks />
        </div>
        <UserBlock />
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-background/90 px-4 backdrop-blur lg:hidden">
          <Logo />
          <Button variant="ghost" size="icon" aria-label="Открыть меню" onClick={() => setOpen(true)}>
            <Menu aria-hidden />
          </Button>
        </header>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent side="left" className="flex flex-col justify-between bg-sidebar p-4">
            <DialogTitle className="sr-only">Меню</DialogTitle>
            <DialogDescription className="sr-only">Навигация по разделам Qadam Media</DialogDescription>
            <div className="space-y-6">
              <Logo className="px-2 pt-1" />
              <NavLinks onNavigate={() => setOpen(false)} />
            </div>
            <UserBlock />
          </DialogContent>
        </Dialog>
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export function RequireAuth() {
  const { user, isLoading, isError, refetch } = useAuth()
  const location = useLocation()
  if (isLoading) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-8" role="status" aria-label="Загрузка">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (isError) {
    return (
      <div className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 p-6 text-center">
        <p className="font-medium">Не удалось связаться с сервером</p>
        <Button onClick={() => refetch()}>Повторить</Button>
      </div>
    )
  }
  if (!user) {
    const next = location.pathname + location.search
    return <Navigate to={next && next !== '/' ? `/login?next=${encodeURIComponent(next)}` : '/login'} replace />
  }
  return <AppShell />
}
