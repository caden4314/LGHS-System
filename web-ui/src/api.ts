import { useQuery } from '@tanstack/react-query'
import { mockSnapshot } from './mock'
import type { FleetSnapshot } from './types'

const useMock = import.meta.env.DEV && import.meta.env.VITE_LGHS_MOCK !== '0'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      // Cloudflare Access recommends this header for SPA/AJAX requests so an
      // expired Access session is returned as 401 instead of becoming a
      // confusing HTML/login response inside fetch().
      'X-Requested-With': 'XMLHttpRequest',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json() as { detail?: string; error?: string }
      detail = body.detail || body.error || detail
    } catch {
      // The status code is still authoritative when no JSON error body exists.
    }
    throw new ApiError(response.status, detail)
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
    // The managed agent reports every ~5 seconds. Until SSE invalidation is
    // available, this keeps the UI current without polling faster than the
    // source can provide useful state.
    refetchInterval: useMock ? false : 5_000,
    staleTime: 3_000,
    retry: (count, error) => !(error instanceof ApiError && [401, 403].includes(error.status)) && count < 2,
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
    refetchInterval: 60_000,
    retry: false,
  })
}
