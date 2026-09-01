import { Activity, Cpu, HardDrive, MemoryStick, Radio, Server, Thermometer, Wifi } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { fleetWrite, useSession } from '../api'
import { EmptyTelemetry } from '../EmptyTelemetry'
import { fmtAge, fmtPercent, fmtRate, fmtSignal, fmtTemp, fmtUptime, Panel, Stat, StatusBadge } from '../components'
import type { DeviceSummary, FleetSnapshot, HealthState } from '../types'

interface HealthRow { name: string; state: HealthState; observed: string; expected: string }

function healthRows(device: DeviceSummary): HealthRow[] {
  return [
    { name: 'Temperature', state: (device.tempC ?? 0) >= 80 ? 'critical' : (device.tempC ?? 0) >= 70 ? 'warning' : 'healthy', observed: fmtTemp(device.tempC), expected: '< 75°C' },
    { name: 'Root storage', state: (device.diskPct ?? 0) >= 96 ? 'critical' : (device.diskPct ?? 0) >= 90 ? 'warning' : 'healthy', observed: fmtPercent(device.diskPct), expected: '< 90%' },
    { name: 'Wi-Fi signal', state: (device.wifiDbm ?? -50) <= -82 ? 'warning' : 'healthy', observed: fmtSignal(device.wifiDbm), expected: '>= -82 dBm' },
    { name: 'Power / throttling', state: device.undervoltage || device.throttled ? 'critical' : 'healthy', observed: device.undervoltage ? 'Undervoltage' : device.throttled ? 'Throttled' : 'Normal', expected: 'Normal' },
    { name: 'Fleet transport', state: device.connectivity === 'offline' ? 'critical' : device.connectivity === 'stale' ? 'warning' : 'healthy', observed: device.connectivity, expected: 'online' },
  ]
}

export function DevicePage({ snapshot }: { snapshot: FleetSnapshot }) {
  const { deviceId = '' } = useParams()
  const device = snapshot.devices.find((row) => row.deviceId.toUpperCase() === deviceId.toUpperCase())
  const session = useSession()
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (!device) return <div className="page-stack"><div className="page-heading"><div><p className="eyebrow">Fleet</p><h1>Device not found</h1><p>The selected device is not in the current controller snapshot.</p></div></div><Link className="button secondary inline-button" to="/fleet">Back to Fleet</Link></div>

  const rows = healthRows(device)
  const deviceActivity = snapshot.activity.filter((item) => item.deviceId === device.deviceId).slice(0, 8)
  const activeAlerts = snapshot.alerts.filter((item) => item.deviceId === device.deviceId && !item.acknowledged)
  const canWrite = session.data?.role === 'owner' || session.data?.role === 'operator'

  async function action(name: 'lghs-update' | 'os-update' | 'reboot' | 'check' | 'enforce' | 'logs') {
    if ((name === 'reboot' || name === 'enforce') && !window.confirm(`${name === 'reboot' ? 'Reboot' : 'Enforce policy on'} ${device!.deviceId}?`)) return
    setBusy(name); setError(null); setResult(null)
    try {
      const response = await fleetWrite<{ result?: { stdout?: string; stderr?: string; commandId?: string } }>(`/api/v1/devices/${encodeURIComponent(device!.deviceId)}/actions/${name}`, session.data?.csrfToken)
      setResult(response.result?.stdout || response.result?.stderr || (response.result?.commandId ? `Queued command ${response.result.commandId}` : 'Operation accepted.'))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="page-stack">
      <div className="device-heading">
        <div>
          <div className="breadcrumb"><Link to="/fleet">Fleet</Link><span>/</span><span>{device.deviceId}</span></div>
          <div className="device-title-line"><h1>{device.deviceId}</h1><StatusBadge tone={device.connectivity} label={device.connectivity} /><StatusBadge tone={device.health} label={device.health} /></div>
          <p>{device.model} · {device.group}</p>
        </div>
        <div className="device-actions">
          <button className="button secondary" type="button" disabled={!canWrite || busy !== null} onClick={() => void action('check')}>Validate</button>
          <button className="button secondary" type="button" disabled={!canWrite || busy !== null} onClick={() => void action('enforce')}>Enforce + validate</button>
          <button className="button primary" type="button" disabled={!canWrite || busy !== null} onClick={() => void action('lghs-update')}>LGHS update</button>
        </div>
      </div>

      {(error || result) && <Panel title={error ? 'Operation failed' : 'Operation result'}><pre className="mono">{error || result}</pre></Panel>}

      <div className="device-context-strip">
        <div><span>Version</span><strong>{device.version}</strong></div>
        <div><span>Commit</span><strong className="mono">{device.commit.slice(0, 12)}</strong></div>
        <div><span>Uptime</span><strong>{fmtUptime(device.uptimeSeconds)}</strong></div>
        <div><span>Last report</span><strong>{fmtAge(device.lastSeenSeconds)} ago</strong></div>
        <div><span>RAM</span><strong>{device.ramMb ? `${(device.ramMb / 1024).toFixed(device.ramMb % 1024 ? 1 : 0)} GB` : '—'}</strong></div>
      </div>

      <div className="stat-grid stat-grid-device">
        <Stat label="CPU" value={fmtPercent(device.cpuPct)} detail="current utilization" tone={(device.cpuPct ?? 0) >= 90 ? 'critical' : 'neutral'} />
        <Stat label="Memory" value={fmtPercent(device.memPct)} detail="current utilization" tone={(device.memPct ?? 0) >= 92 ? 'warning' : 'neutral'} />
        <Stat label="Disk" value={fmtPercent(device.diskPct)} detail="root filesystem" tone={(device.diskPct ?? 0) >= 90 ? 'warning' : 'neutral'} />
        <Stat label="Temperature" value={fmtTemp(device.tempC)} detail="SoC" tone={(device.tempC ?? 0) >= 80 ? 'critical' : (device.tempC ?? 0) >= 70 ? 'warning' : 'neutral'} />
        <Stat label="Wi-Fi" value={fmtSignal(device.wifiDbm)} detail={device.ssid || 'signal strength'} tone={(device.wifiDbm ?? 0) <= -82 ? 'warning' : 'neutral'} />
      </div>

      <div className="dashboard-grid dashboard-grid-main">
        <Panel title="Telemetry" description="Historical retention is the next data-path stage" className="span-2"><EmptyTelemetry /></Panel>
        <Panel title="Health" description={`${activeAlerts.length} active alert${activeAlerts.length === 1 ? '' : 's'}`}>
          <div className="health-list">{rows.map((row) => <div className="health-row" key={row.name}><StatusBadge tone={row.state} label={row.name} /><div><span>{row.observed}</span><small>Expected {row.expected}</small></div></div>)}</div>
        </Panel>
      </div>

      <div className="dashboard-grid dashboard-grid-secondary">
        <Panel title="System" description="Current inventory and runtime facts">
          <dl className="detail-list">
            <div><dt><Server aria-hidden="true" /> Model</dt><dd>{device.model}</dd></div>
            <div><dt><Cpu aria-hidden="true" /> CPU</dt><dd>{fmtPercent(device.cpuPct)}</dd></div>
            <div><dt><MemoryStick aria-hidden="true" /> Memory</dt><dd>{fmtPercent(device.memPct)}</dd></div>
            <div><dt><HardDrive aria-hidden="true" /> Root disk</dt><dd>{fmtPercent(device.diskPct)}</dd></div>
            <div><dt><Thermometer aria-hidden="true" /> Temperature</dt><dd>{fmtTemp(device.tempC)}</dd></div>
            <div><dt>Load</dt><dd>{device.load1?.toFixed(2) ?? '—'}</dd></div>
          </dl>
        </Panel>

        <Panel title="Network" description="Connectivity and current traffic">
          <dl className="detail-list">
            <div><dt><Wifi aria-hidden="true" /> Wi-Fi</dt><dd>{device.ssid ? `${device.ssid} · ` : ''}{fmtSignal(device.wifiDbm)}</dd></div>
            <div><dt>Interface</dt><dd>{device.activeInterface ?? '—'}</dd></div>
            <div><dt>IPv4</dt><dd className="mono">{device.ipv4?.join(', ') || '—'}</dd></div>
            <div><dt>Gateway</dt><dd className="mono">{device.gateway ?? '—'}</dd></div>
            <div><dt><Radio aria-hidden="true" /> RX</dt><dd>{fmtRate(device.rxBps)}</dd></div>
            <div><dt><Radio aria-hidden="true" /> TX</dt><dd>{fmtRate(device.txBps)}</dd></div>
            <div><dt>RX dropped/errors</dt><dd>{device.rxDropped ?? '—'} / {device.rxErrors ?? '—'}</dd></div>
            <div><dt>TX dropped/errors</dt><dd>{device.txDropped ?? '—'} / {device.txErrors ?? '—'}</dd></div>
          </dl>
        </Panel>

        <Panel title="LGHS" description="Managed software state">
          <dl className="detail-list">
            <div><dt>Release</dt><dd>{device.version}</dd></div>
            <div><dt>Commit</dt><dd className="mono">{device.commit.slice(0, 12)}</dd></div>
            <div><dt>Role</dt><dd>{device.role}</dd></div>
            <div><dt>Update</dt><dd>{device.updateState ?? 'idle'}</dd></div>
            <div><dt>Reboot required</dt><dd>{device.rebootRequired ? 'yes' : 'no'}</dd></div>
            <div><dt>Boot ID</dt><dd className="mono">{device.bootId?.slice(0, 12) ?? '—'}</dd></div>
          </dl>
          <div className="inline-actions">
            <button className="button secondary compact" type="button" disabled={!canWrite || busy !== null} onClick={() => void action('os-update')}>OS update</button>
            <button className="button secondary compact" type="button" disabled={!canWrite || busy !== null} onClick={() => void action('logs')}>Logs</button>
            <button className="button secondary compact" type="button" disabled={!canWrite || busy !== null} onClick={() => void action('reboot')}>Reboot</button>
          </div>
        </Panel>
      </div>

      <Panel title="Recent activity" description="Device-scoped operational events">
        {deviceActivity.length ? <div className="activity-list">{deviceActivity.map((item) => <div className="activity-row" key={item.id}><Activity aria-hidden="true" /><div><strong>{item.kind}</strong><span>{item.message}</span></div>{item.actor && <span className="activity-actor">{item.actor}</span>}<time>{new Date(item.at).toLocaleString()}</time></div>)}</div> : <p className="muted">No recent device events.</p>}
      </Panel>
    </div>
  )
}
