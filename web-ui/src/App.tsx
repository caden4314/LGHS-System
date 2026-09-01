import { Activity, AlertTriangle, Bell, Boxes, ChevronDown, Command, LayoutDashboard, Search, Settings, ShieldCheck, Users } from 'lucide-react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router'
import { useFleetSnapshot, useSession } from './api'
import { LoginBoundary } from './LoginBoundary'
import { ThemeToggle } from './ThemeToggle'
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

  if (session.isLoading || fleet.isLoading) return <LoginBoundary mode="loading" />
  if (session.isError || !session.data?.authenticated) {
    return <LoginBoundary mode="error" detail="Cloudflare Access or LGHS authorization could not verify this session." />
  }
  if (fleet.isError || !fleet.data) {
    return <FatalState title="Fleet data unavailable" detail="Authentication succeeded, but the controller gateway did not return a valid fleet snapshot." />
  }

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
          <div className="controller-status"><span className="status-dot" aria-hidden="true" /><div><strong>Controller connected</strong><span>Gateway snapshot received</span></div></div>
          <div className="build-label">LGHS 0.6 · Web preview</div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <Link className="global-search" to="/fleet" aria-label="Open fleet search">
            <Search aria-hidden="true" /><span>Search fleet</span>
          </Link>
          <div className="topbar-actions">
            <ThemeToggle />
            <Link className="icon-button" to="/alerts" aria-label="Open alerts"><Bell aria-hidden="true" />{criticalAlerts > 0 && <span className="notification-dot" />}</Link>
            <a className="identity-button" href="/cdn-cgi/access/logout" aria-label={`Signed in as ${identity.email}. Sign out of Cloudflare Access.`} title="Sign out">
              <span className="avatar" aria-hidden="true">{identity.email.charAt(0).toUpperCase()}</span>
              <span className="identity-copy"><strong>{identity.email}</strong><small>{identity.role}</small></span>
              <ChevronDown aria-hidden="true" />
            </a>
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

function FatalState({ title, detail }: { title: string; detail: string }) {
  return <div className="center-state error-state"><AlertTriangle aria-hidden="true" /><strong>{title}</strong><span>{detail}</span><button className="button secondary" onClick={() => window.location.reload()} type="button">Retry</button></div>
}
