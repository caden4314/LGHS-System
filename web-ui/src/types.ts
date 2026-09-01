export type HealthState = 'healthy' | 'warning' | 'critical' | 'maintenance' | 'unknown'
export type ConnectivityState = 'online' | 'stale' | 'offline'
export type Severity = 'info' | 'warning' | 'critical'
export type DeploymentState = 'queued' | 'running' | 'paused' | 'succeeded' | 'failed' | 'canceled'

export interface DeviceSummary {
  deviceId: string
  hostname: string
  health: HealthState
  connectivity: ConnectivityState
  version: string
  commit: string
  role: 'student' | 'controller'
  group: string
  tags: string[]
  model: string
  ramMb: number
  cpuPct: number | null
  memPct: number | null
  diskPct: number | null
  tempC: number | null
  wifiDbm: number | null
  rxBps: number | null
  txBps: number | null
  uptimeSeconds: number | null
  lastSeenSeconds: number | null
  updateState: string | null
  rebootRequired: boolean
  throttled: boolean
  undervoltage: boolean
}

export interface FleetAlert {
  id: string
  deviceId: string | null
  severity: Severity
  kind: string
  title: string
  detail: string
  observed?: string
  expected?: string
  ageSeconds: number
  acknowledged: boolean
}

export interface DeploymentSummary {
  id: string
  name: string
  version: string
  commit: string
  state: DeploymentState
  completed: number
  total: number
  phase: number
  phases: number
  createdAt: string
}

export interface ActivityItem {
  id: string
  at: string
  deviceId?: string
  severity: Severity
  kind: string
  message: string
  actor?: string
}

export interface FleetSnapshot {
  devices: DeviceSummary[]
  alerts: FleetAlert[]
  deployments: DeploymentSummary[]
  activity: ActivityItem[]
  generatedAt: string
}
