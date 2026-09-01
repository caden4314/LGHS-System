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
      // Keep the HTTP status when a proxy returned a non-JSON body.
    }
    throw new ApiError(response.status, detail)
  }

  return response.json() as Promise<T>
}

export async function getFleetSnapshot(): Promise<FleetSnapshot> {
  if (useMock) {
    await new Promise((resolve) => window.setTimeout(resolve, 120))
    return { ...mockSnapshot, generatedAt: new Date().toISOString() }
  }
  return requestJson<FleetSnapshot>('/api/v1/overview')
}

export function useFleetSnapshot() {
  return useQuery({
    queryKey: ['fleet', 'overview'],
    queryFn: getFleetSnapshot,
    refetchInterval: useMock ? false : 5_000,
    staleTime: 3_000,
    // Keep the last successful snapshot visible while a transient controller
    // request retries. The gateway also serves a bounded last-good snapshot.
    placeholderData: (previousData) => previousData,
    retry: (count, error) => !(error instanceof ApiError && [401, 403].includes(error.status)) && count < 4,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8_000),
  })
}

export interface SessionInfo {
  authenticated: boolean
  email: string
  role: 'owner' | 'operator' | 'viewer'
  csrfToken?: string
}

export async function getSession(): Promise<SessionInfo> {
  if (useMock) return { authenticated: true, email: 'operator@scenicrouteservers.com', role: 'owner', csrfToken: 'mock' }
  return requestJson<SessionInfo>('/api/v1/session')
}

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: getSession,
    staleTime: 5 * 60_000,
    // Do not intentionally revalidate Access every minute. Access itself
    // enforces the session on every proxied API request.
    refetchInterval: false,
    retry: false,
  })
}

export async function fleetWrite<T>(path: string, csrfToken: string | undefined, method = 'POST', body?: unknown): Promise<T> {
  if (useMock) return { ok: true } as T
  if (!csrfToken) throw new ApiError(403, 'Missing CSRF token; refresh the authenticated session.')
  return requestJson<T>(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-LGHS-CSRF': csrfToken,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}
