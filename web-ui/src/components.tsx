import type { PropsWithChildren, ReactNode } from 'react'
import { CircleAlert, CircleCheck, CircleDot, CircleX, LoaderCircle, Minus } from 'lucide-react'
import type { ConnectivityState, HealthState, Severity } from './types'

export function Panel({ title, description, action, children, className = '' }: PropsWithChildren<{ title?: string; description?: string; action?: ReactNode; className?: string }>) {
  return (
    <section className={`panel ${className}`.trim()}>
      {(title || description || action) && (
        <header className="panel-header">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p>{description}</p>}
          </div>
          {action && <div className="panel-action">{action}</div>}
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  )
}

export function StatusBadge({ tone, label }: { tone: HealthState | ConnectivityState | Severity | 'updating'; label: string }) {
  const icon = tone === 'healthy' || tone === 'online'
    ? <CircleCheck aria-hidden="true" />
    : tone === 'critical' || tone === 'offline'
      ? <CircleX aria-hidden="true" />
      : tone === 'warning' || tone === 'stale'
        ? <CircleAlert aria-hidden="true" />
        : tone === 'updating'
          ? <LoaderCircle aria-hidden="true" />
          : tone === 'maintenance'
            ? <Minus aria-hidden="true" />
            : <CircleDot aria-hidden="true" />

  return <span className={`status-badge tone-${tone}`}>{icon}<span>{label}</span></span>
}

export function Stat({ label, value, detail, tone = 'neutral' }: { label: string; value: ReactNode; detail?: ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'critical' }) {
  return (
    <div className={`stat stat-${tone}`}>
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {detail && <span className="stat-detail">{detail}</span>}
    </div>
  )
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <CircleCheck aria-hidden="true" />
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  )
}

export function fmtPercent(value: number | null) {
  return value == null ? '—' : `${value.toFixed(value >= 10 ? 0 : 1)}%`
}

export function fmtTemp(value: number | null) {
  return value == null ? '—' : `${value.toFixed(1)}°C`
}

export function fmtSignal(value: number | null) {
  return value == null ? '—' : `${Math.round(value)} dBm`
}

export function fmtRate(value: number | null) {
  if (value == null) return '—'
  let n = value
  for (const unit of ['B/s', 'KB/s', 'MB/s', 'GB/s']) {
    if (n < 1024) return `${n < 10 ? n.toFixed(1) : Math.round(n)} ${unit}`
    n /= 1024
  }
  return `${n.toFixed(1)} TB/s`
}

export function fmtAge(seconds: number | null) {
  if (seconds == null) return '—'
  if (seconds < 10) return `${seconds.toFixed(1)}s`
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

export function fmtUptime(seconds: number | null) {
  if (seconds == null) return '—'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return `${days}d ${hours}h`
  if (hours) return `${hours}h ${minutes}m`
  return `${minutes}m`
}
