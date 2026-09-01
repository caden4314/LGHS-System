import { Activity, AlertTriangle, Bell, Boxes, ChevronDown, Command, LayoutDashboard, Search, Settings, ShieldCheck, Users } from 'lucide-react'
import { NavLink, Navigate, Route, Routes } from 'react-router'
import { useFleetSnapshot, useSession } from './api'
import { OverviewPage } from './pages/Overview'
import { FleetPage } from './pages/Fleet'
import { DevicePage } from './pages/Device'
import { ActivityPage, AlertsPage, DeploymentsPage, GroupsPage, SettingsPage, SudoPage } from './pages/Sections'

const navigation = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/fleet', label: 'Fleet', icon: Boxes },
  { to: '/alerts', label: 'Alerts', icon: AlertTriangle },
  { to: '/deployments', label: 'Deployments', icon: Command },
  { to: '/sudo', label: 'Sudo', icon: ShieldCheck },
  { to: '/activity', label: 'Activity', icon: Activity },
  { to: '/groups', label: 'Groups', icon: Users },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export default function App() {
  const fleet = useFleetSnapshot()
  const session = useSession()

  if (fleet.isLoading || session.isLoading) return <LoadingShell />
  if (fleet.isError || !fleet.data) return <FatalState title="Fleet data unavailable" detail="The controller web gateway did not return a valid fleet snapshot." />
  if (session.isError || !session.data?.authenticated) return <FatalState title="Session unavailable" detail="Authentication information could not be verified by the web gateway." />

  const snapshot = fleet.data
  const identity = session.data
  const criticalAlerts = snapshot.alerts.filter((alert) => alert.severity === 'critical' && !alert.acknowledged).length

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">LG</div>
          <div><strong>LGHS Fleet</strong><span>Operations</span></div>
        </div>

        <nav className="primary-nav" aria-label="Primary navigation">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
              <Icon aria-hidden="true" />
              <span>{label}</span>
              {label === 'Alerts' && criticalAlerts > 0 && <span className="nav-count" aria-label={`${criticalAlerts} critical alerts`}>{criticalAlerts}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="controller-status"><span className="status-dot" aria-hidden="true" /><div><strong>Controller online</strong><span>Fleet API responding</span></div></div>
          <div className="build-label">LGHS 0.6 · Web preview</div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <button className="global-search" type="button" aria-label="Open global search">
            <Search aria-hidden="true" /><span>Search fleet</span><kbd>⌘ K</kbd>
          </button>
          <div className="topbar-actions">
            <button className="icon-button" type="button" aria-label="Notifications"><Bell aria-hidden="true" />{criticalAlerts > 0 && <span className="notification-dot" />}</button>
            <button className="identity-button" type="button" aria-label="Account menu">
              <span className="avatar" aria-hidden="true">{identity.email.charAt(0).toUpperCase()}</span>
              <span className="identity-copy"><strong>{identity.email}</strong><small>{identity.role}</small></span>
              <ChevronDown aria-hidden="true" />
            </button>
          </div>
        </header>

        <main className="main-content">
          <Routes>
            <Route path="/" element={<OverviewPage snapshot={snapshot} />} />
            <Route path="/fleet" element={<FleetPage devices={snapshot.devices} />} />
            <Route path="/fleet/:deviceId" element={<DevicePage snapshot={snapshot} />} />
            <Route path="/alerts" element={<AlertsPage snapshot={snapshot} />} />
            <Route path="/deployments" element={<DeploymentsPage snapshot={snapshot} />} />
            <Route path="/deployments/:deploymentId" element={<DeploymentsPage snapshot={snapshot} />} />
            <Route path="/sudo" element={<SudoPage />} />
            <Route path="/activity" element={<ActivityPage snapshot={snapshot} />} />
            <Route path="/groups" element={<GroupsPage snapshot={snapshot} />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

function LoadingShell() {
  return <div className="center-state" role="status"><div className="loading-mark" aria-hidden="true" /><strong>Loading Fleet</strong><span>Connecting to controller…</span></div>
}

function FatalState({ title, detail }: { title: string; detail: string }) {
  return <div className="center-state error-state"><AlertTriangle aria-hidden="true" /><strong>{title}</strong><span>{detail}</span><button className="button secondary" onClick={() => window.location.reload()} type="button">Retry</button></div>
}
