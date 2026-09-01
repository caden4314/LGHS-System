import { Activity, Cpu, HardDrive, MemoryStick, Radio, Server, Thermometer, Wifi } from 'lucide-react'
import { Link, useParams } from 'react-router'
import { fmtAge, fmtPercent, fmtRate, fmtSignal, fmtTemp, fmtUptime, Panel, Stat, StatusBadge } from '../components'
import { TelemetryChart, type TelemetryPoint } from '../TelemetryChart'
import type { DeviceSummary, FleetSnapshot, HealthState } from '../types'

function historyFor(device: DeviceSummary): TelemetryPoint[] {
  const now = Date.now()
  const baseCpu = device.cpuPct ?? 8
  const baseMem = device.memPct ?? 30
  return Array.from({ length: 60 }, (_, index) => {
    const phase = index / 6
    return {
      at: now - (59 - index) * 60_000,
      cpuPct: Math.max(0, Math.min(100, baseCpu + Math.sin(phase) * 5 + Math.sin(phase * 2.7) * 2)),
      memPct: Math.max(0, Math.min(100, baseMem + Math.sin(phase / 2) * 2.5)),
    }
  })
}

interface HealthRow {
  name: string
  state: HealthState
  observed: string
  expected: string
}

function healthRows(device: DeviceSummary): HealthRow[] {
  const rows: HealthRow[] = []
  rows.push({
    name: 'Temperature',
    state: (device.tempC ?? 0) >= 80 ? 'critical' : (device.tempC ?? 0) >= 70 ? 'warning' : 'healthy',
    observed: fmtTemp(device.tempC),
    expected: '< 75°C',
  })
  rows.push({
    name: 'Root storage',
    state: (device.diskPct ?? 0) >= 96 ? 'critical' : (device.diskPct ?? 0) >= 90 ? 'warning' : 'healthy',
    observed: fmtPercent(device.diskPct),
    expected: '< 90%',
  })
  rows.push({
    name: 'Wi-Fi signal',
    state: (device.wifiDbm ?? -50) <= -82 ? 'warning' : 'healthy',
    observed: fmtSignal(device.wifiDbm),
    expected: '>= -82 dBm',
  })
  rows.push({
    name: 'Power / throttling',
    state: device.undervoltage || device.throttled ? 'critical' : 'healthy',
    observed: device.undervoltage ? 'Undervoltage' : device.throttled ? 'Throttled' : 'Normal',
    expected: 'Normal',
  })
  rows.push({
    name: 'Fleet transport',
    state: device.connectivity === 'offline' ? 'critical' : device.connectivity === 'stale' ? 'warning' : 'healthy',
    observed: device.connectivity,
    expected: 'online',
  })
  return rows
}

export function DevicePage({ snapshot }: { snapshot: FleetSnapshot }) {
  const { deviceId = '' } = useParams()
  const device = snapshot.devices.find((row) => row.deviceId.toUpperCase() === deviceId.toUpperCase())

  if (!device) {
    return (
      <div className="page-stack">
        <div className="page-heading"><div><p className="eyebrow">Fleet</p><h1>Device not found</h1><p>The selected device is not in the current controller snapshot.</p></div></div>
        <Link className="button secondary inline-button" to="/fleet">Back to Fleet</Link>
      </div>
    )
  }

  const rows = healthRows(device)
  const deviceActivity = snapshot.activity.filter((item) => item.deviceId === device.deviceId).slice(0, 8)
  const activeAlerts = snapshot.alerts.filter((item) => item.deviceId === device.deviceId && !item.acknowledged)

  return (
    <div className="page-stack">
      <div className="device-heading">
        <div>
          <div className="breadcrumb"><Link to="/fleet">Fleet</Link><span>/</span><span>{device.deviceId}</span></div>
          <div className="device-title-line">
            <h1>{device.deviceId}</h1>
            <StatusBadge tone={device.connectivity} label={device.connectivity} />
            <StatusBadge tone={device.health} label={device.health} />
          </div>
          <p>{device.model} · {device.group}</p>
        </div>
        <div className="device-actions">
          <button className="button secondary" type="button">Maintenance</button>
          <button className="button primary" type="button">Actions</button>
        </div>
      </div>

      <div className="device-context-strip">
        <div><span>Version</span><strong>{device.version}</strong></div>
        <div><span>Commit</span><strong className="mono">{device.commit.slice(0, 12)}</strong></div>
        <div><span>Uptime</span><strong>{fmtUptime(device.uptimeSeconds)}</strong></div>
        <div><span>Last report</span><strong>{fmtAge(device.lastSeenSeconds)} ago</strong></div>
        <div><span>RAM</span><strong>{(device.ramMb / 1024).toFixed(device.ramMb % 1024 ? 1 : 0)} GB</strong></div>
      </div>

      <div className="stat-grid stat-grid-device">
        <Stat label="CPU" value={fmtPercent(device.cpuPct)} detail="current utilization" tone={(device.cpuPct ?? 0) >= 90 ? 'critical' : 'neutral'} />
        <Stat label="Memory" value={fmtPercent(device.memPct)} detail="current utilization" tone={(device.memPct ?? 0) >= 92 ? 'warning' : 'neutral'} />
        <Stat label="Disk" value={fmtPercent(device.diskPct)} detail="root filesystem" tone={(device.diskPct ?? 0) >= 90 ? 'warning' : 'neutral'} />
        <Stat label="Temperature" value={fmtTemp(device.tempC)} detail="SoC" tone={(device.tempC ?? 0) >= 80 ? 'critical' : (device.tempC ?? 0) >= 70 ? 'warning' : 'neutral'} />
        <Stat label="Wi-Fi" value={fmtSignal(device.wifiDbm)} detail="signal strength" tone={(device.wifiDbm ?? 0) <= -82 ? 'warning' : 'neutral'} />
      </div>

      <div className="dashboard-grid dashboard-grid-main">
        <Panel title="Telemetry" description={import.meta.env.DEV ? 'Last hour · development sample until the history endpoint is connected' : 'Last hour'} className="span-2">
          <TelemetryChart points={historyFor(device)} />
        </Panel>

        <Panel title="Health" description={`${activeAlerts.length} active alert${activeAlerts.length === 1 ? '' : 's'}`}>
          <div className="health-list">
            {rows.map((row) => (
              <div className="health-row" key={row.name}>
                <StatusBadge tone={row.state} label={row.name} />
                <div><span>{row.observed}</span><small>Expected {row.expected}</small></div>
              </div>
            ))}
          </div>
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
          </dl>
        </Panel>

        <Panel title="Network" description="Connectivity and current traffic">
          <dl className="detail-list">
            <div><dt><Wifi aria-hidden="true" /> Wi-Fi</dt><dd>{fmtSignal(device.wifiDbm)}</dd></div>
            <div><dt><Radio aria-hidden="true" /> RX</dt><dd>{fmtRate(device.rxBps)}</dd></div>
            <div><dt><Radio aria-hidden="true" /> TX</dt><dd>{fmtRate(device.txBps)}</dd></div>
            <div><dt>Fleet state</dt><dd>{device.connectivity}</dd></div>
            <div><dt>Last report</dt><dd>{fmtAge(device.lastSeenSeconds)} ago</dd></div>
          </dl>
        </Panel>

        <Panel title="LGHS" description="Managed software state">
          <dl className="detail-list">
            <div><dt>Release</dt><dd>{device.version}</dd></div>
            <div><dt>Commit</dt><dd className="mono">{device.commit.slice(0, 12)}</dd></div>
            <div><dt>Role</dt><dd>{device.role}</dd></div>
            <div><dt>Update</dt><dd>{device.updateState ?? 'idle'}</dd></div>
            <div><dt>Reboot required</dt><dd>{device.rebootRequired ? 'yes' : 'no'}</dd></div>
          </dl>
        </Panel>
      </div>

      <Panel title="Recent activity" description="Device-scoped operational events">
        {deviceActivity.length ? (
          <div className="activity-list">
            {deviceActivity.map((item) => (
              <div className="activity-row" key={item.id}>
                <Activity aria-hidden="true" />
                <div><strong>{item.kind}</strong><span>{item.message}</span></div>
                {item.actor && <span className="activity-actor">{item.actor}</span>}
                <time>{new Date(item.at).toLocaleString()}</time>
              </div>
            ))}
          </div>
        ) : <p className="muted">No recent device events in the current snapshot.</p>}
      </Panel>
    </div>
  )
}
