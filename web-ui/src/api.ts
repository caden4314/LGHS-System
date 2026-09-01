import { useQuery } from '@tanstack/react-query'
import { mockSnapshot } from './mock'
import type { FleetSnapshot } from './types'

const useMock = import.meta.env.DEV && import.meta.env.VITE_LGHS_MOCK !== '0'

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`)
  }

  return response.json() as Promise<T>
}

export async function getFleetSnapshot(): Promise<FleetSnapshot> {
  if (useMock) {
    await new Promise((resolve) => window.setTimeout(resolve, 120))
    return {
      ...mockSnapshot,
      generatedAt: new Date().toISOString(),
    }
  }

  return requestJson<FleetSnapshot>('/api/v1/overview')
}

export function useFleetSnapshot() {
  return useQuery({
    queryKey: ['fleet', 'overview'],
    queryFn: getFleetSnapshot,
    refetchInterval: useMock ? false : 15_000,
    staleTime: 5_000,
    retry: 2,
  })
}

export interface SessionInfo {
  authenticated: boolean
  email: string
  role: 'owner' | 'operator' | 'viewer'
  csrfToken?: string
}

export async function getSession(): Promise<SessionInfo> {
  if (useMock) {
    return {
      authenticated: true,
      email: 'operator@scenicrouteservers.com',
      role: 'owner',
    }
  }
  return requestJson<SessionInfo>('/api/v1/session')
}

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: getSession,
    staleTime: 60_000,
    retry: false,
  })
}
