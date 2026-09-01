import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, KeyRound, Layers3, Settings2, ShieldCheck, Users } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { fleetWrite, useSession } from '../api'
import { EmptyState, fmtAge, fmtPercent, fmtRate, fmtSignal, fmtTemp, Panel, StatusBadge } from '../components'
import type { FleetSnapshot, SudoRequest } from '../types'

function useWrite() {
  const session = useSession()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  async function run(key: string, path: string, method = 'POST', body?: unknown) {
    setBusy(key); setError(null)
    try {
      await fleetWrite(path, session.data?.csrfToken, method, body)
      window.setTimeout(() => window.location.reload(), 150)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err)); setBusy(null)
    }
  }
  return { session: session.data, busy, error, run }
}

export function AlertsPage({ snapshot }: { snapshot: FleetSnapshot }) {
  const writer = useWrite()
  const alerts = snapshot.alerts.slice().sort((a, b) => {
    const rank = { critical: 0, warning: 1, info: 2 }
    return Number(a.acknowledged) - Number(b.acknowledged) || rank[a.severity] - rank[b.severity] || b.ageSeconds - a.ageSeconds
  })
  return (
    <Section title="Alerts" eyebrow="Health" description="Actionable fleet issues, ordered by severity and age.">
      {writer.error && <WriteError text={writer.error} />}
      <Panel>
        {alerts.length ? <div className="alert-table-wrap"><table className="alert-table"><caption className="sr-only">Active LGHS fleet alerts</caption><thead><tr><th>Severity</th><th>Device</th><th>Issue</th><th>Observed</th><th>Expected</th><th>Age</th><th>Action</th></tr></thead><tbody>{alerts.map((alert) => <tr key={alert.id}><td><StatusBadge tone={alert.severity} label={alert.severity} /></td><td>{alert.deviceId ? <Link className="device-link" to={`/fleet/${alert.deviceId}`}>{alert.deviceId}</Link> : 'Fleet'}</td><td><strong>{alert.title}</strong><span className="table-subline">{alert.detail}</span></td><td>{alert.observed ?? '—'}</td><td>{alert.expected ?? '—'}</td><td>{fmtAge(alert.ageSeconds)}</td><td>{alert.acknowledged ? <span className="muted">Acknowledged</span> : <button className="button ghost compact" type="button" disabled={writer.busy === alert.id || writer.session?.role === 'viewer'} onClick={() => writer.run(alert.id, `/api/v1/alerts/${encodeURIComponent(alert.id)}/ack`)}>{writer.busy === alert.id ? 'Saving…' : 'Acknowledge'}</button>}</td></tr>)}</tbody></table></div> : <EmptyState title="No active warnings" detail="No unresolved controller warnings are present." />}
      </Panel>
    </Section>
  )
}

export function DeploymentsPage({ snapshot }: { snapshot: FleetSnapshot }) {
  const writer = useWrite()
  const canWrite = writer.session?.role === 'owner' || writer.session?.role === 'operator'
  function createDeployment() {
    const commit = window.prompt('Exact 40-character target commit SHA')?.trim()
    if (!commit) return
    const version = window.prompt('Target version label (example: 0.6.0-dev)', '0.6.0-dev')?.trim() || undefined
    const target = window.prompt('Target device ID, or type ALL for the entire student fleet', 'CS-999')?.trim()
    if (!target) return
    const name = window.prompt('Deployment name', `Deploy ${commit.slice(0, 12)}`)?.trim() || `Deploy ${commit.slice(0, 12)}`
    const selector = target.toUpperCase() === 'ALL' ? { all: true } : { device_id: target.toUpperCase() }
    void writer.run('new-deployment', '/api/v1/deployments', 'POST', { name, target_commit: commit, target_version: version, target: selector, dispatch: true, auto: false, respect_maintenance: true })
  }
  function deploymentAction(id: string, action: string, body: unknown = {}) {
    const destructive = action === 'cancel-remaining' || action === 'rollback'
    if (destructive && !window.confirm(`${action.replace('-', ' ')} deployment ${id.slice(0, 12)}?`)) return
    void writer.run(`${id}:${action}`, `/api/v1/deployments/${encodeURIComponent(id)}/${action}`, 'POST', body)
  }
  return (
    <Section title="Deployments" eyebrow="Updates" description="Controlled exact-commit LGHS rollouts with recovery controls." action={<button className="button primary" type="button" disabled={!canWrite || writer.busy !== null} onClick={createDeployment}>New deployment</button>}>
      {writer.error && <WriteError text={writer.error} />}
      <Panel>
        {snapshot.deployments.length ? <div className="deployment-list">{snapshot.deployments.map((deployment) => {
          const progress = deployment.total ? Math.round((deployment.completed / deployment.total) * 100) : 0
          return <div className="deployment-list-row" key={deployment.id}><div className="deployment-state"><StatusBadge tone={deployment.state === 'failed' ? 'critical' : deployment.state === 'running' ? 'updating' : 'healthy'} label={deployment.state} /></div><div><Link className="device-link" to={`/deployments/${deployment.id}`}><strong>{deployment.name}</strong></Link><span className="mono">{deployment.version} · {deployment.commit.slice(0, 12)}</span></div><div><span className="small-label">Progress</span><strong>{deployment.completed}/{deployment.total}</strong></div><div><span className="small-label">Wave</span><strong>{deployment.phase}/{deployment.phases}</strong></div><div className="mini-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div><div className="inline-actions"><button className="button ghost compact" type="button" disabled={!canWrite || writer.busy !== null} onClick={() => deploymentAction(deployment.id, 'advance')}>Advance</button><button className="button ghost compact" type="button" disabled={!canWrite || writer.busy !== null} onClick={() => deploymentAction(deployment.id, 'retry-failed')}>Retry failed</button><button className="button ghost compact" type="button" disabled={!canWrite || writer.busy !== null} onClick={() => deploymentAction(deployment.id, 'resume')}>Resume</button><button className="button ghost compact" type="button" disabled={!canWrite || writer.busy !== null} onClick={() => deploymentAction(deployment.id, 'rollback', { dispatch: true, auto: false })}>Rollback</button><button className="button ghost compact" type="button" disabled={!canWrite || writer.busy !== null} onClick={() => deploymentAction(deployment.id, 'cancel-remaining')}>Cancel remaining</button></div></div>
        })}</div> : <EmptyState title="No deployments" detail="No deployment records are currently stored." />}
      </Panel>
    </Section>
  )
}

function sudoKey(row: SudoRequest) { return String(row.request_id || row.id || '') }

export function SudoPage({ snapshot }: { snapshot: FleetSnapshot }) {
  const writer = useWrite(); const requests = (snapshot.sudoRequests ?? []).filter((row) => row.state === 'pending')
  return (
    <Section title="Sudo approvals" eyebrow="Security" description="Review the exact privileged request before granting or denying one-time access.">
      {writer.error && <WriteError text={writer.error} />}
      <Panel>{requests.length ? <div className="alert-table-wrap"><table className="alert-table"><thead><tr><th>Device</th><th>Requester</th><th>Command</th><th>Working directory</th><th>Age</th><th>Expires</th><th>Decision</th></tr></thead><tbody>{requests.map((row) => { const id = sudoKey(row); const age = Math.max(0, Date.now()/1000-Number(row.requested_at||0)); const expires=row.expires_at?Math.max(0,Number(row.expires_at)-Date.now()/1000):null; return <tr key={id}><td><Link className="device-link" to={`/fleet/${row.device_id}`}>{row.device_id}</Link></td><td>{row.requester ?? 'unknown'}</td><td><strong className="mono">{row.command}</strong>{row.argv?.length ? <span className="table-subline mono">argv: {JSON.stringify(row.argv)}</span>:null}<span className="table-subline mono">request: {id}</span></td><td className="mono">{row.cwd ?? '—'}</td><td>{fmtAge(age)}</td><td>{expires===null?'—':`${Math.round(expires)}s`}</td><td><div className="inline-actions"><button className="button primary compact" type="button" disabled={writer.busy===id||writer.session?.role==='viewer'} onClick={()=>writer.run(id,`/api/v1/sudo/${encodeURIComponent(id)}/approve`)}>Approve</button><button className="button secondary compact" type="button" disabled={writer.busy===id||writer.session?.role==='viewer'} onClick={()=>writer.run(id,`/api/v1/sudo/${encodeURIComponent(id)}/deny`)}>Deny</button></div></td></tr> })}</tbody></table></div> : <EmptyState title="No pending sudo requests" detail="New student sudo requests will appear here automatically from Fleet telemetry." />}</Panel>
      <Panel title="Approval model" description="The hosted UI preserves the original Fleet console security model"><div className="feature-grid"><InfoBlock icon={<KeyRound />} title="Exact request" text="Device, requester, command, argv, cwd, request ID, age and expiry are visible before a decision." /><InfoBlock icon={<Clock3 />} title="Time bounded" text="Only the original unexpired request can be approved. Resolved requests are no longer actionable." /><InfoBlock icon={<ShieldCheck />} title="Audited" text="The controller records the authenticated Cloudflare Access identity alongside each web decision." /></div></Panel>
    </Section>
  )
}

export function ActivityPage({ snapshot }: { snapshot: FleetSnapshot }) {
  return <Section title="Activity" eyebrow="Audit" description="Chronological operational record across updates, health, sudo, reboots, and enrollment."><Panel>{snapshot.activity.length ? <div className="timeline">{snapshot.activity.map((item)=><div className="timeline-row" key={item.id}><span className={`timeline-dot tone-${item.severity}`} aria-hidden="true" /><time>{new Date(item.at).toLocaleString()}</time><div><strong>{item.deviceId ?? 'Fleet'} · {item.kind}</strong><span>{item.message}</span></div><span className="activity-actor">{item.actor ?? 'system'}</span></div>)}</div> : <EmptyState title="No activity yet" detail="The controller audit database has no recent events." />}</Panel></Section>
}

export function GroupsPage({ snapshot }: { snapshot: FleetSnapshot }) {
  const writer=useWrite(); const groups=Array.from(new Set(snapshot.devices.filter((device)=>device.role!=='controller').map((device)=>device.group))).sort(); const canWrite=writer.session?.role==='owner'||writer.session?.role==='operator'
  function create(){const name=window.prompt('New Fleet group name')?.trim();if(!name)return;const description=window.prompt('Description (optional)')??'';void writer.run('create-group','/api/v1/groups','POST',{name,description})}
  function add(group:string){const device=window.prompt(`Device ID to add to ${group}`)?.trim().toUpperCase();if(!device)return;const target=snapshot.devices.find((row)=>row.deviceId===device);if(!target){window.alert('That device is not in the current Fleet snapshot.');return}void writer.run(`add:${group}:${device}`,`/api/v1/groups/${encodeURIComponent(group)}/members/${encodeURIComponent(device)}`)}
  function remove(group:string){const device=window.prompt(`Device ID to remove from ${group}`)?.trim().toUpperCase();if(!device)return;void writer.run(`remove:${group}:${device}`,`/api/v1/groups/${encodeURIComponent(group)}/members/${encodeURIComponent(device)}`,'DELETE')}
  return <Section title="Groups" eyebrow="Organization" description="Durable operational scopes for policy, maintenance, and deployments." action={<button className="button primary" type="button" disabled={!canWrite||writer.busy==='create-group'} onClick={create}>Create group</button>}>{writer.error&&<WriteError text={writer.error}/>}<div className="group-grid">{groups.map((group)=>{const members=snapshot.devices.filter((device)=>device.group===group);const issues=members.filter((device)=>device.health==='critical'||device.health==='warning'||device.connectivity!=='online').length;return <Panel key={group} className="group-card"><div className="group-title"><Users aria-hidden="true"/><div><strong>{group}</strong><span>{members.length} device{members.length===1?'':'s'}</span></div></div><div className="group-facts"><span>{issues?`${issues} need attention`:'All healthy'}</span><span>{members.filter((device)=>device.version.startsWith('0.6')).length}/{members.length} on 0.6</span></div><div className="inline-actions"><button className="button secondary compact" type="button" disabled={!canWrite||writer.busy!==null} onClick={()=>add(group)}>Add device</button><button className="button secondary compact" type="button" disabled={!canWrite||writer.busy!==null} onClick={()=>remove(group)}>Remove device</button></div><Link className="button secondary full-width group-fleet-link" to={`/fleet?group=${encodeURIComponent(group)}`}>View devices</Link></Panel>})}</div></Section>
}

export function SettingsPage({ snapshot }: { snapshot: FleetSnapshot }) {
  const writer=useWrite(); const controller=snapshot.controller; const report=controller?.report??{}; const services=controller?.services??{}; const metrics=controller?.metrics; const network=metrics?.network
  function edit(key:string,current:unknown){const raw=window.prompt(`JSON value for ${key}`,JSON.stringify(current??{},null,2));if(raw===null)return;try{void writer.run(key,`/api/v1/settings/${key}`,'PUT',{value:JSON.parse(raw)})}catch{window.alert('That is not valid JSON.')}}
  const setting=(key:string)=>snapshot.settings?.[key]?.value
  return <Section title="Settings" eyebrow="Controller" description="Fleet-wide operational defaults and live controller health.">{writer.error&&<WriteError text={writer.error}/>}<Panel title="Controller telemetry" description={`${report.hostname??'LGCSCONT'} · ${report.version??'unknown version'} · ${String(report.commit??'').slice(0,12)}`}><div className="feature-grid"><InfoBlock icon={<Settings2/>} title="CPU" text={fmtPercent(metrics?.cpu_pct??null)}/><InfoBlock icon={<Settings2/>} title="Memory" text={fmtPercent(metrics?.mem_pct??null)}/><InfoBlock icon={<Settings2/>} title="Disk" text={fmtPercent(metrics?.disk_pct??null)}/><InfoBlock icon={<Settings2/>} title="Temperature" text={fmtTemp(metrics?.temp_c??null)}/><InfoBlock icon={<Settings2/>} title="Wi-Fi" text={`${network?.ssid??'—'} · ${fmtSignal(network?.signal_dbm??null)}`}/><InfoBlock icon={<Settings2/>} title="Traffic" text={`RX ${fmtRate(network?.rx_bps??null)} · TX ${fmtRate(network?.tx_bps??null)}`}/></div></Panel><Panel title="Controller services" description="Fleet API, web, tunnels, Bluetooth and reconciliation state"><div className="feature-grid">{Object.entries(services).map(([unit,state])=><InfoBlock key={unit} icon={<Settings2/>} title={unit} text={state}/>)}</div></Panel><div className="settings-list"><SettingsRow icon={<Layers3/>} title="Telemetry retention" detail={JSON.stringify(setting('web.telemetry_retention')??{})} action={()=>edit('web.telemetry_retention',setting('web.telemetry_retention'))} disabled={writer.session?.role!=='owner'}/><SettingsRow icon={<AlertTriangle/>} title="Health thresholds" detail={JSON.stringify(setting('web.health_thresholds')??{})} action={()=>edit('web.health_thresholds',setting('web.health_thresholds'))} disabled={writer.session?.role!=='owner'}/><SettingsRow icon={<CheckCircle2/>} title="Update defaults" detail={JSON.stringify(setting('web.update_defaults')??{})} action={()=>edit('web.update_defaults',setting('web.update_defaults'))} disabled={writer.session?.role!=='owner'}/><SettingsRow icon={<Settings2/>} title="Controller defaults" detail={JSON.stringify(setting('web.controller_defaults')??{})} action={()=>edit('web.controller_defaults',setting('web.controller_defaults'))} disabled={writer.session?.role!=='owner'}/></div></Section>
}

function Section({title,eyebrow,description,action,children}:{title:string;eyebrow:string;description:string;action?:React.ReactNode;children:React.ReactNode}){return <div className="page-stack"><div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>{action&&<div>{action}</div>}</div>{children}</div>}
function InfoBlock({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div className="info-block"><span>{icon}</span><div><strong>{title}</strong><p>{text}</p></div></div>}
function SettingsRow({icon,title,detail,action,disabled}:{icon:React.ReactNode;title:string;detail:string;action:()=>void;disabled?:boolean}){return <div className="settings-row"><span className="settings-icon">{icon}</span><span><strong>{title}</strong><small>{detail}</small></span><button className="button secondary compact" type="button" onClick={action} disabled={disabled}>Edit</button></div>}
function WriteError({text}:{text:string}){return <div className="center-state error-state"><AlertTriangle aria-hidden="true"/><strong>Operation failed</strong><span>{text}</span></div>}
