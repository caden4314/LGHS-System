import { Search, SlidersHorizontal } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { fmtAge, fmtPercent, fmtSignal, fmtTemp, fmtUptime, Panel, StatusBadge } from '../components'
import type { DeviceSummary } from '../types'

function deviceStatus(device: DeviceSummary) {
  if (device.connectivity !== 'online') return <StatusBadge tone={device.connectivity} label={device.connectivity} />
  if (device.updateState) return <StatusBadge tone="updating" label={device.updateState} />
  return <StatusBadge tone={device.health} label={device.health} />
}

export function FleetPage({ devices }: { devices: DeviceSummary[] }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return devices.filter((device) => {
      const matchesQuery = !needle || [device.deviceId, device.hostname, device.group, device.version, ...device.tags]
        .some((value) => value.toLowerCase().includes(needle))
      const matchesStatus = status === 'all'
        || status === device.connectivity
        || status === device.health
        || (status === 'updating' && Boolean(device.updateState))
      return matchesQuery && matchesStatus
    })
  }, [devices, query, status])

  function toggle(deviceId: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(deviceId)) next.delete(deviceId)
      else next.add(deviceId)
      return next
    })
  }

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Inventory</p>
          <h1>Fleet</h1>
          <p>Search, compare, and open any managed Raspberry Pi.</p>
        </div>
      </div>

      <Panel className="fleet-panel">
        <div className="table-toolbar">
          <label className="search-field">
            <Search aria-hidden="true" />
            <span className="sr-only">Search devices</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search device, group, tag, or version" />
          </label>
          <label className="filter-field">
            <SlidersHorizontal aria-hidden="true" />
            <span>Status</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="all">All</option>
              <option value="healthy">Healthy</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
              <option value="updating">Updating</option>
              <option value="stale">Stale</option>
              <option value="offline">Offline</option>
            </select>
          </label>
          <span className="result-count" role="status">{filtered.length} device{filtered.length === 1 ? '' : 's'}</span>
          {selected.size > 0 && <button className="button secondary" type="button">Actions for {selected.size}</button>}
        </div>

        <div className="fleet-table-wrap" tabIndex={0} aria-label="Managed devices table; scroll horizontally for more columns">
          <table className="fleet-table">
            <caption className="sr-only">Managed LGHS Raspberry Pi fleet</caption>
            <thead>
              <tr>
                <th className="selection-cell"><span className="sr-only">Select</span></th>
                <th>Device</th>
                <th>Status</th>
                <th>Version</th>
                <th>Group</th>
                <th className="numeric">CPU</th>
                <th className="numeric">RAM</th>
                <th className="numeric">Disk</th>
                <th className="numeric">Temp</th>
                <th className="numeric">Wi-Fi</th>
                <th>Uptime</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((device) => (
                <tr key={device.deviceId} className={selected.has(device.deviceId) ? 'selected-row' : ''}>
                  <td className="selection-cell"><input aria-label={`Select ${device.deviceId}`} type="checkbox" checked={selected.has(device.deviceId)} onChange={() => toggle(device.deviceId)} /></td>
                  <td className="device-cell">
                    <Link to={`/fleet/${device.deviceId}`} className="device-link">{device.deviceId}</Link>
                    <span className="device-subline">{device.model.replace('Raspberry Pi ', 'Pi ')}</span>
                  </td>
                  <td>{deviceStatus(device)}</td>
                  <td><span className="version-cell">{device.version}</span><span className="mono commit-short">{device.commit.slice(0, 8)}</span></td>
                  <td>{device.group}</td>
                  <td className="numeric">{fmtPercent(device.cpuPct)}</td>
                  <td className="numeric">{fmtPercent(device.memPct)}</td>
                  <td className={`numeric ${(device.diskPct ?? 0) >= 90 ? 'value-warning' : ''}`}>{fmtPercent(device.diskPct)}</td>
                  <td className={`numeric ${(device.tempC ?? 0) >= 80 ? 'value-critical' : (device.tempC ?? 0) >= 70 ? 'value-warning' : ''}`}>{fmtTemp(device.tempC)}</td>
                  <td className={`numeric ${(device.wifiDbm ?? 0) <= -80 ? 'value-warning' : ''}`}>{fmtSignal(device.wifiDbm)}</td>
                  <td>{fmtUptime(device.uptimeSeconds)}</td>
                  <td>{fmtAge(device.lastSeenSeconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
