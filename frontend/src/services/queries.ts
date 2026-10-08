import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { accountsApi, authApi, miscApi, publicationsApi } from '@/services/api'
import type { PublicationStatus } from '@/types/api'
import { isActiveStatus } from '@/utils/status'

export const keys = {
  meta: ['meta'] as const,
  dashboard: ['dashboard'] as const,
  accounts: ['accounts'] as const,
  creator: (id: string) => ['creator-info', id] as const,
  publications: (params: object) => ['publications', params] as const,
  publication: (id: string) => ['publication', id] as const,
  audit: (params: object) => ['audit', params] as const,
  sessions: ['sessions'] as const,
}

export const useMeta = () => useQuery({ queryKey: keys.meta, queryFn: miscApi.meta, staleTime: 10 * 60_000 })

export const useDashboard = () =>
  useQuery({
    queryKey: keys.dashboard,
    queryFn: miscApi.dashboard,
    refetchInterval: (q) => ((q.state.data?.in_progress ?? 0) > 0 ? 5_000 : false),
  })

export const useAccounts = () => useQuery({ queryKey: keys.accounts, queryFn: accountsApi.list })

export const useCreatorInfo = (accountId: string | undefined) =>
  useQuery({
    queryKey: keys.creator(accountId ?? ''),
    queryFn: () => accountsApi.creatorInfo(accountId!),
    enabled: !!accountId,
    staleTime: 0, // TikTok guidelines: always fetch fresh creator info when the posting form is shown
    gcTime: 0,
    retry: false,
  })

export const usePublications = (params: { status?: PublicationStatus; limit: number; offset: number }) =>
  useQuery({
    queryKey: keys.publications(params),
    queryFn: () => publicationsApi.list(params),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((p) => isActiveStatus(p.status)) ? 4_000 : false),
  })

export const usePublication = (id: string) =>
  useQuery({
    queryKey: keys.publication(id),
    queryFn: () => publicationsApi.get(id),
    refetchInterval: (q) => (q.state.data && isActiveStatus(q.state.data.status) ? 3_000 : false),
  })

export const useAuditLogs = (params: { limit: number; offset: number }) =>
  useQuery({ queryKey: keys.audit(params), queryFn: () => miscApi.auditLogs(params), placeholderData: keepPreviousData })

export const useSessions = () => useQuery({ queryKey: keys.sessions, queryFn: authApi.sessions })
