import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, KeyRound, Layers3, Settings2, ShieldCheck, Users } from 'lucide-react'
import { Link } from 'react-router'
import { EmptyState, fmtAge, Panel, StatusBadge } from '../components'
import type { FleetSnapshot } from '../types'

export function AlertsPage({ snapshot }: { snapshot: FleetSnapshot }) {
  const alerts = snapshot.alerts.slice().sort((a, b) => {
    const rank = { critical: 0, warning: 1, info: 2 }
    return Number(a.acknowledged) - Number(b.acknowledged) || rank[a.severity] - rank[b.severity] || b.ageSeconds - a.ageSeconds
  })
  return (
    <Section title="Alerts" eyebrow="Health" description="Actionable fleet issues, ordered by severity and age.">
      <Panel>
        {alerts.length ? (
          <div className="alert-table-wrap">
            <table className="alert-table">
              <caption className="sr-only">Active LGHS fleet alerts</caption>
              <thead><tr><th>Severity</th><th>Device</th><th>Issue</th><th>Observed</th><th>Expected</th><th>Age</th><th>Action</th></tr></thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td><StatusBadge tone={alert.severity} label={alert.severity} /></td>
                    <td>{alert.deviceId ? <Link className="device-link" to={`/fleet/${alert.deviceId}`}>{alert.deviceId}</Link> : 'Fleet'}</td>
                    <td><strong>{alert.title}</strong><span className="table-subline">{alert.detail}</span></td>
                    <td>{alert.observed ?? '—'}</td>
                    <td>{alert.expected ?? '—'}</td>
                    <td>{fmtAge(alert.ageSeconds)}</td>
                    <td><button className="button ghost compact" type="button" disabled title="Alert acknowledgment will be enabled with the audited write gateway">Acknowledge</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="No active warnings in the current read model" detail="The controller warning cache did not return an unresolved warning." />}
      </Panel>
    </Section>
  )
}

export function DeploymentsPage({ snapshot }: { snapshot: FleetSnapshot }) {
  return (
    <Section
      title="Deployments"
      eyebrow="Updates"
      description="Observe controlled LGHS rollouts. Creation and recovery actions remain disabled until the audited write gateway is tested."
      action={<button className="button primary" type="button" disabled title="Enabled after write-gateway acceptance">New deployment</button>}
    >
      <Panel>
        {snapshot.deployments.length ? (
          <div className="deployment-list">
            {snapshot.deployments.map((deployment) => {
              const progress = deployment.total ? Math.round((deployment.completed / deployment.total) * 100) : 0
              return (
                <Link className="deployment-list-row" to={`/deployments/${deployment.id}`} key={deployment.id}>
                  <div className="deployment-state"><StatusBadge tone={deployment.state === 'failed' ? 'critical' : deployment.state === 'running' ? 'updating' : 'healthy'} label={deployment.state} /></div>
                  <div><strong>{deployment.name}</strong><span className="mono">{deployment.version} · {deployment.commit.slice(0, 12)}</span></div>
                  <div><span className="small-label">Progress</span><strong>{deployment.completed}/{deployment.total}</strong></div>
                  <div><span className="small-label">Wave</span><strong>{deployment.phase}/{deployment.phases}</strong></div>
                  <div className="mini-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label={`${deployment.name} ${progress}% complete`}><span style={{ width: `${progress}%` }} /></div>
                  <ArrowRight aria-hidden="true" />
                </Link>
              )
            })}
          </div>
        ) : <EmptyState title="No deployments" detail="The controller has no deployment records in the current read model." />}
      </Panel>
    </Section>
  )
}

export function SudoPage() {
  return (
    <Section title="Sudo approvals" eyebrow="Security" description="Review exact privileged commands before granting one-time approval.">
      <Panel>
        <div className="empty-operational">
          <ShieldCheck aria-hidden="true" />
          <div><strong>Sudo request feed is not connected yet</strong><p>The first hosted build is read-only. We will wire the controller sudo request store before approval/denial controls are enabled.</p></div>
        </div>
      </Panel>
      <Panel title="Approval model" description="What an operator must see before making a decision">
        <div className="feature-grid">
          <InfoBlock icon={<KeyRound />} title="Exact request" text="Show argv, working directory, requester, device, request ID, age, and expiry. Never hide arguments behind a summary." />
          <InfoBlock icon={<Clock3 />} title="Time bounded" text="Expired requests disappear from the actionable queue and approval is valid only for the original request." />
          <InfoBlock icon={<ShieldCheck />} title="Audited" text="Approval and denial are written with the authenticated web identity and linked back to the request." />
        </div>
      </Panel>
    </Section>
  )
}

export function ActivityPage({ snapshot }: { snapshot: FleetSnapshot }) {
  return (
    <Section title="Activity" eyebrow="Audit" description="One chronological operational record across updates, health, sudo, reboots, and enrollment.">
      <Panel>
        {snapshot.activity.length ? (
          <div className="timeline">
            {snapshot.activity.map((item) => (
              <div className="timeline-row" key={item.id}>
                <span className={`timeline-dot tone-${item.severity}`} aria-hidden="true" />
                <time>{new Date(item.at).toLocaleString()}</time>
                <div><strong>{item.deviceId ?? 'Fleet'} · {item.kind}</strong><span>{item.message}</span></div>
                <span className="activity-actor">{item.actor ?? 'system'}</span>
              </div>
            ))}
          </div>
        ) : <EmptyState title="Activity feed is not connected yet" detail="Audit events exist on the controller; the web read endpoint is still being integrated." />}
      </Panel>
    </Section>
  )
}

export function GroupsPage({ snapshot }: { snapshot: FleetSnapshot }) {
  const groups = Array.from(new Set(snapshot.devices.map((device) => device.group))).sort()
  return (
    <Section
      title="Groups"
      eyebrow="Organization"
      description="Use groups and tags as durable operational scopes for policy, maintenance, and deployments."
      action={<button className="button primary" type="button" disabled title="Group mutation is disabled in the read-only preview">Create group</button>}
    >
      <div className="group-grid">
        {groups.map((group) => {
          const members = snapshot.devices.filter((device) => device.group === group)
          const issues = members.filter((device) => device.health === 'critical' || device.health === 'warning' || device.connectivity !== 'online').length
          return (
            <Panel key={group} className="group-card">
              <div className="group-title"><Users aria-hidden="true" /><div><strong>{group}</strong><span>{members.length} device{members.length === 1 ? '' : 's'}</span></div></div>
              <div className="group-facts"><span>{issues ? `${issues} need attention` : 'All healthy'}</span><span>{members.filter((device) => device.version.startsWith('0.6')).length}/{members.length} on 0.6</span></div>
              <Link className="button secondary full-width group-fleet-link" to={`/fleet?group=${encodeURIComponent(group)}`}>View devices</Link>
            </Panel>
          )
        })}
      </div>
    </Section>
  )
}

export function SettingsPage() {
  return (
    <Section title="Settings" eyebrow="Controller" description="Planned Fleet-wide operational defaults and web console configuration.">
      <div className="settings-list" aria-label="Planned settings areas">
        <SettingsRow icon={<ShieldCheck />} title="Access & roles" detail="Cloudflare Access identity mapping, owner/operator/viewer permissions, and step-up rules." />
        <SettingsRow icon={<Layers3 />} title="Telemetry retention" detail="High-resolution retention, rollup periods, and long-term history policy." />
        <SettingsRow icon={<AlertTriangle />} title="Health thresholds" detail="Temperature, disk, memory, Wi-Fi, and connectivity warning thresholds." />
        <SettingsRow icon={<CheckCircle2 />} title="Update defaults" detail="Health gates, rollout wave defaults, maintenance behavior, and verification timeouts." />
        <SettingsRow icon={<Settings2 />} title="Controller & tunnel" detail="Web gateway, Fleet API, database, build version, and UI tunnel health." />
      </div>
    </Section>
  )
}

function Section({ title, eyebrow, description, action, children }: { title: string; eyebrow: string; description: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>{action && <div>{action}</div>}</div>
      {children}
    </div>
  )
}

function InfoBlock({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return <div className="info-block"><span>{icon}</span><div><strong>{title}</strong><p>{text}</p></div></div>
}

function SettingsRow({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) {
  return <div className="settings-row settings-row-readonly"><span className="settings-icon">{icon}</span><span><strong>{title}</strong><small>{detail}</small></span><span className="preview-label">Planned</span></div>
}
