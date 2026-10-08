import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Toaster } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ThemeProvider, useTheme } from '@/hooks/use-theme'
import { ME_KEY } from '@/hooks/use-auth'
import { ApiError, setUnauthorizedHandler } from '@/services/http'

export function createQueryClient() {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache(),
    mutationCache: new MutationCache(),
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      },
    },
  })
  // an expired/revoked session anywhere sends the user back to the login screen
  setUnauthorizedHandler(() => client.setQueryData(ME_KEY, null))
  return client
}

function ThemedToaster() {
  const { theme } = useTheme()
  return <Toaster theme={theme} position="top-right" richColors closeButton />
}

export function AppProviders({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? createQueryClient())
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={200}>
          {children}
          <ThemedToaster />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
