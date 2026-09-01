export type HealthState = 'healthy' | 'warning' | 'critical' | 'maintenance' | 'unknown'
export type ConnectivityState = 'online' | 'stale' | 'offline'
export type Severity = 'info' | 'warning' | 'critical'
export type DeploymentState = 'queued' | 'running' | 'paused' | 'succeeded' | 'failed' | 'canceled'

export interface NetworkTelemetry {
  active_interface?: string | null
  state?: string | null
  ipv4?: string[]
  ipv6?: string[]
  gateway?: string | null
  source?: string | null
  metric?: number | null
  ssid?: string | null
  signal_dbm?: number | null
  rx_bitrate?: string | null
  tx_bitrate?: string | null
  rx_bps?: number | null
  tx_bps?: number | null
  rx_bytes?: number | null
  tx_bytes?: number | null
  rx_packets?: number | null
  tx_packets?: number | null
  rx_errors?: number | null
  tx_errors?: number | null
  rx_dropped?: number | null
  tx_dropped?: number | null
}

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
  load1?: number | null
  wifiDbm: number | null
  ssid?: string | null
  activeInterface?: string | null
  ipv4?: string[]
  ipv6?: string[]
  gateway?: string | null
  rxBps: number | null
  txBps: number | null
  rxBytes?: number | null
  txBytes?: number | null
  rxErrors?: number | null
  txErrors?: number | null
  rxDropped?: number | null
  txDropped?: number | null
  uptimeSeconds: number | null
  lastSeenSeconds: number | null
  bootId?: string | null
  sequence?: number | null
  transport?: Record<string, unknown> | null
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

export interface SudoRequest {
  request_id?: string
  id?: string
  device_id: string
  state: string
  command: string
  requested_at: number
  updated_at: number
  expires_at?: number | null
  requester?: string
  argv?: string[]
  cwd?: string
  approved_by?: string
  denied_by?: string
  authorization?: string
}

export interface ControllerMetrics {
  cpu_pct?: number | null
  mem_pct?: number | null
  disk_pct?: number | null
  temp_c?: number | null
  load1?: number | null
  uptime_seconds?: number | null
  network?: NetworkTelemetry
}

export interface ControllerStatus {
  services?: Record<string, string>
  report?: Record<string, string>
  metrics?: ControllerMetrics
  observedAt?: number
}

export interface FleetSnapshot {
  devices: DeviceSummary[]
  alerts: FleetAlert[]
  deployments: DeploymentSummary[]
  activity: ActivityItem[]
  sudoRequests?: SudoRequest[]
  settings?: Record<string, { value: unknown; updatedAt: number }>
  controller?: ControllerStatus
  generatedAt: string
  degraded?: boolean
}
