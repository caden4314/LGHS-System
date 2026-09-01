import { ArrowRight, Cpu, HardDrive, MemoryStick, Radio, Server, Thermometer, Wifi } from 'lucide-react'
import { Link } from 'react-router'
import { EmptyState, fmtAge, fmtPercent, fmtSignal, fmtTemp, Panel, Stat, StatusBadge } from '../components'
import { OverviewSignal } from '../OverviewSignal'
import type { FleetSnapshot, Severity } from '../types'

function severityTone(severity: Severity) {
  return severity === 'critical' ? 'critical' : severity === 'warning' ? 'warning' : 'info'
}

export function OverviewPage({ snapshot }: { snapshot: FleetSnapshot }) {
  const devices = snapshot.devices
  const online = devices.filter((d) => d.connectivity === 'online').length
  const critical = devices.filter((d) => d.health === 'critical' || d.connectivity === 'offline').length
  const warning = devices.filter((d) => d.health === 'warning' || d.connectivity === 'stale').length
  const updating = devices.filter((d) => Boolean(d.updateState)).length
  const unresolved = snapshot.alerts.filter((a) => !a.acknowledged)
  const attention = unresolved.slice().sort((a, b) => {
    const rank = { critical: 0, warning: 1, info: 2 }
    return rank[a.severity] - rank[b.severity] || b.ageSeconds - a.ageSeconds
  }).slice(0, 6)

  const hottest = devices.filter((d) => d.tempC != null).slice().sort((a, b) => (b.tempC ?? 0) - (a.tempC ?? 0)).slice(0, 4)

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Fleet overview</h1>
          <p>Current fleet health, active work, and the devices that need attention.</p>
        </div>
        <div className="freshness" role="status">Snapshot {new Date(snapshot.generatedAt).toLocaleTimeString()}</div>
      </div>

      <OverviewSignal online={online} total={devices.length} critical={critical} />

      <div className="stat-grid">
        <Stat label="Online" value={`${online}/${devices.length}`} detail="reporting now" tone={online === devices.length ? 'success' : 'neutral'} />
        <Stat label="Critical" value={critical} detail="requires attention" tone={critical ? 'critical' : 'success'} />
        <Stat label="Warnings" value={warning} detail="degraded state" tone={warning ? 'warning' : 'success'} />
        <Stat label="Updating" value={updating} detail="active device jobs" />
      </div>

      <div className="dashboard-grid dashboard-grid-main">
        <Panel
          title="Needs attention"
          description="Actionable health and connectivity issues"
          action={<Link className="text-link" to="/alerts">All alerts <ArrowRight aria-hidden="true" /></Link>}
          className="span-2"
        >
          {attention.length ? (
            <div className="attention-list">
              {attention.map((alert) => (
                <Link to={alert.deviceId ? `/fleet/${alert.deviceId}` : '/alerts'} className="attention-row" key={alert.id}>
                  <StatusBadge tone={severityTone(alert.severity)} label={alert.severity.toUpperCase()} />
                  <div className="attention-copy">
                    <strong>{alert.title}</strong>
                    <span>{alert.deviceId ?? 'Fleet'} · {alert.detail}</span>
                  </div>
                  <time>{fmtAge(alert.ageSeconds)}</time>
                  <ArrowRight className="row-chevron" aria-hidden="true" />
                </Link>
              ))}
            </div>
          ) : <EmptyState title="No active issues" detail="All devices are within configured health thresholds." />}
        </Panel>

        <Panel title="Active deployment" description="Current rollout state">
          {snapshot.deployments.length ? snapshot.deployments.slice(0, 2).map((deployment) => {
            const pct = deployment.total ? Math.round((deployment.completed / deployment.total) * 100) : 0
            return (
              <Link className="deployment-card" to={`/deployments/${deployment.id}`} key={deployment.id}>
                <div className="deployment-topline">
                  <StatusBadge tone={deployment.state === 'failed' ? 'critical' : deployment.state === 'running' ? 'updating' : 'healthy'} label={deployment.state} />
                  <span>Wave {deployment.phase}/{deployment.phases}</span>
                </div>
                <strong>{deployment.name}</strong>
                <span className="mono">{deployment.version} · {deployment.commit.slice(0, 10)}</span>
                <div className="progress-track" aria-label={`${pct}% complete`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                  <span style={{ width: `${pct}%` }} />
                </div>
                <span>{deployment.completed}/{deployment.total} devices complete</span>
              </Link>
            )
          }) : <EmptyState title="No active deployments" detail="The fleet has no current rollout work." />}
        </Panel>
      </div>

      <div className="dashboard-grid dashboard-grid-secondary">
        <Panel title="Resource outliers" description="Highest current values; use trends on a device page for diagnosis" className="span-2">
          <div className="resource-table-wrap">
            <table className="resource-table">
              <caption className="sr-only">Fleet devices with the highest current temperature</caption>
              <thead>
                <tr><th>Device</th><th><Cpu aria-hidden="true" /> CPU</th><th><MemoryStick aria-hidden="true" /> RAM</th><th><HardDrive aria-hidden="true" /> Disk</th><th><Thermometer aria-hidden="true" /> Temp</th><th><Wifi aria-hidden="true" /> Wi-Fi</th></tr>
              </thead>
              <tbody>
                {hottest.map((device) => (
                  <tr key={device.deviceId}>
                    <td><Link className="device-link" to={`/fleet/${device.deviceId}`}>{device.deviceId}</Link></td>
                    <td>{fmtPercent(device.cpuPct)}</td>
                    <td>{fmtPercent(device.memPct)}</td>
                    <td>{fmtPercent(device.diskPct)}</td>
                    <td className={(device.tempC ?? 0) >= 80 ? 'value-critical' : (device.tempC ?? 0) >= 70 ? 'value-warning' : ''}>{fmtTemp(device.tempC)}</td>
                    <td>{fmtSignal(device.wifiDbm)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Fleet composition" description="Useful inventory, not vanity analytics">
          <dl className="compact-facts">
            <div><dt><Server aria-hidden="true" /> Raspberry Pis</dt><dd>{devices.length}</dd></div>
            <div><dt><Radio aria-hidden="true" /> Groups</dt><dd>{new Set(devices.map((d) => d.group)).size}</dd></div>
            <div><dt>LGHS 0.6</dt><dd>{devices.filter((d) => d.version.startsWith('0.6')).length}</dd></div>
            <div><dt>Older version</dt><dd>{devices.filter((d) => !d.version.startsWith('0.6')).length}</dd></div>
          </dl>
        </Panel>
      </div>

      <Panel title="Recent activity" description="Operational events from the controller audit stream" action={<Link className="text-link" to="/activity">View activity <ArrowRight aria-hidden="true" /></Link>}>
        {snapshot.activity.length ? (
          <div className="activity-list">
            {snapshot.activity.slice(0, 6).map((item) => (
              <div className="activity-row" key={item.id}>
                <span className={`activity-marker tone-${item.severity}`} aria-hidden="true" />
                <div>
                  <strong>{item.deviceId ?? 'Fleet'}</strong>
                  <span>{item.message}</span>
                </div>
                {item.actor && <span className="activity-actor">{item.actor}</span>}
                <time>{new Date(item.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
              </div>
            ))}
          </div>
        ) : <EmptyState title="No activity available" detail="The web gateway has not connected the controller audit timeline yet." />}
      </Panel>
    </div>
  )
}
