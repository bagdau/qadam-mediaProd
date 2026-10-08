import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { authApi } from '@/services/api'
import { ApiError } from '@/services/http'
import type { AuthResponse } from '@/types/api'

export const ME_KEY = ['me'] as const

/** Drop every cached query except the session probe. `qc.clear()` would also detach the observers of
 *  `me`, so the router would never learn that the user changed. */
function resetUserData(qc: QueryClient) {
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== ME_KEY[0] })
}

export function useAuth() {
  const query = useQuery<AuthResponse | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await authApi.me()
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  })
  return {
    user: query.data?.user ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  }
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => authApi.login(email, password),
    onSuccess: (data) => {
      resetUserData(qc)
      qc.setQueryData(ME_KEY, data)
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => {
      resetUserData(qc)
      qc.setQueryData(ME_KEY, null)
    },
  })
}
