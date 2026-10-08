import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'
import { Logo } from '@/app/layout'
import { ThemeToggle } from '@/components/shared/theme-toggle'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth, useLogin } from '@/hooks/use-auth'
import { errorMessage } from '@/services/http'

export const loginSchema = z.object({
  email: z.string().trim().min(1, 'Введите адрес почты').email('Некорректный адрес почты'),
  password: z.string().min(1, 'Введите пароль'),
})
type LoginValues = z.infer<typeof loginSchema>

/** Only same-origin relative paths are allowed as a post-login target (no open redirect). */
export function safeNext(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return '/'
  return value
}

const OAUTH_ERRORS: Record<string, string> = {
  session_required: 'Сначала войдите в систему, затем повторите подключение TikTok.',
}

export function LoginPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const login = useLogin()
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: '', password: '' } })

  const oauthError = params.get('oauth_error')
  if (user) return <Navigate to={safeNext(params.get('next'))} replace />

  const onSubmit = handleSubmit(async (values) => {
    try {
      await login.mutateAsync(values)
      navigate(safeNext(params.get('next')), { replace: true })
    } catch (error) {
      const message = errorMessage(error, 'Не удалось войти')
      setError('root', { message })
      toast.error(message)
    }
  })

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 p-4">
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>
      <Logo />
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">Вход</CardTitle>
          <CardDescription>Войдите, чтобы управлять публикациями в TikTok.</CardDescription>
        </CardHeader>
        <CardContent>
          {oauthError && (
            <p role="alert" className="mb-4 rounded-md border border-warning/40 bg-warning-soft p-3 text-sm">
              {OAUTH_ERRORS[oauthError] ?? 'Не удалось завершить подключение TikTok.'}
            </p>
          )}
          <form onSubmit={onSubmit} noValidate className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Адрес почты</Label>
              <Input id="email" type="email" autoComplete="username" inputMode="email" aria-invalid={!!errors.email}
                aria-describedby={errors.email ? 'email-error' : undefined} {...register('email')} />
              {errors.email && <p id="email-error" className="text-sm text-destructive">{errors.email.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Пароль</Label>
              <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password}
                aria-describedby={errors.password ? 'password-error' : undefined} {...register('password')} />
              {errors.password && <p id="password-error" className="text-sm text-destructive">{errors.password.message}</p>}
            </div>
            {errors.root && <p role="alert" className="text-sm text-destructive">{errors.root.message}</p>}
            <Button type="submit" className="w-full" loading={login.isPending}>
              Войти
            </Button>
          </form>
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        <Link className="underline-offset-4 hover:underline" to="/terms">Условия использования</Link>
        {' · '}
        <Link className="underline-offset-4 hover:underline" to="/privacy">Политика конфиденциальности</Link>
      </p>
    </div>
  )
}
