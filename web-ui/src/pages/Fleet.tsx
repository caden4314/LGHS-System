import { ArrowDown, ArrowUp, ArrowUpDown, Search, SlidersHorizontal } from 'lucide-react'
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { fmtAge, fmtPercent, fmtSignal, fmtTemp, fmtUptime, Panel, StatusBadge } from '../components'
import type { DeviceSummary } from '../types'

function deviceStatus(device: DeviceSummary) {
  if (device.connectivity !== 'online') return <StatusBadge tone={device.connectivity} label={device.connectivity} />
  if (device.updateState) return <StatusBadge tone="updating" label={device.updateState} />
  return <StatusBadge tone={device.health} label={device.health} />
}

function statusRank(device: DeviceSummary) {
  if (device.connectivity === 'offline') return 0
  if (device.health === 'critical') return 1
  if (device.connectivity === 'stale') return 2
  if (device.health === 'warning') return 3
  if (device.updateState) return 4
  return 5
}

function nullableNumberSort(a: { original: DeviceSummary }, b: { original: DeviceSummary }, key: keyof DeviceSummary) {
  const av = a.original[key]
  const bv = b.original[key]
  const an = typeof av === 'number' ? av : Number.NEGATIVE_INFINITY
  const bn = typeof bv === 'number' ? bv : Number.NEGATIVE_INFINITY
  return an === bn ? 0 : an > bn ? 1 : -1
}

export function FleetPage({ devices }: { devices: DeviceSummary[] }) {
  const [params, setParams] = useSearchParams()
  const [sorting, setSorting] = useState<SortingState>([{ id: 'device', desc: false }])
  const query = params.get('q') ?? ''
  const status = params.get('status') ?? 'all'
  const group = params.get('group') ?? 'all'

  const groups = useMemo(() => Array.from(new Set(devices.map((device) => device.group))).sort(), [devices])
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return devices.filter((device) => {
      const matchesQuery = !needle || [device.deviceId, device.hostname, device.group, device.version, ...device.tags]
        .some((value) => value.toLowerCase().includes(needle))
      const matchesStatus = status === 'all'
        || status === device.connectivity
        || status === device.health
        || (status === 'updating' && Boolean(device.updateState))
      const matchesGroup = group === 'all' || group === device.group
      return matchesQuery && matchesStatus && matchesGroup
    })
  }, [devices, group, query, status])

  function updateParam(name: string, value: string, emptyValue = 'all') {
    const next = new URLSearchParams(params)
    if (!value || value === emptyValue) next.delete(name)
    else next.set(name, value)
    setParams(next, { replace: true })
  }

  const columns = useMemo<ColumnDef<DeviceSummary>[]>(() => [
    {
      id: 'device',
      accessorFn: (device) => device.deviceId,
      header: 'Device',
      cell: ({ row }) => (
        <div className="device-cell">
          <Link to={`/fleet/${row.original.deviceId}`} className="device-link">{row.original.deviceId}</Link>
          <span className="device-subline">{row.original.model.replace('Raspberry Pi ', 'Pi ')}</span>
        </div>
      ),
      sortingFn: 'alphanumeric',
    },
    {
      id: 'status',
      accessorFn: statusRank,
      header: 'Status',
      cell: ({ row }) => deviceStatus(row.original),
      sortingFn: 'basic',
    },
    {
      id: 'version',
      accessorFn: (device) => device.version,
      header: 'Version',
      cell: ({ row }) => <><span className="version-cell">{row.original.version}</span><span className="mono commit-short">{row.original.commit.slice(0, 8)}</span></>,
      sortingFn: 'alphanumeric',
    },
    { id: 'group', accessorFn: (device) => device.group, header: 'Group', sortingFn: 'alphanumeric' },
    { id: 'cpu', accessorFn: (device) => device.cpuPct, header: 'CPU', cell: ({ row }) => fmtPercent(row.original.cpuPct), sortingFn: (a, b) => nullableNumberSort(a, b, 'cpuPct'), meta: { numeric: true } },
    { id: 'ram', accessorFn: (device) => device.memPct, header: 'RAM', cell: ({ row }) => fmtPercent(row.original.memPct), sortingFn: (a, b) => nullableNumberSort(a, b, 'memPct'), meta: { numeric: true } },
    {
      id: 'disk', accessorFn: (device) => device.diskPct, header: 'Disk',
      cell: ({ row }) => <span className={(row.original.diskPct ?? 0) >= 90 ? 'value-warning' : ''}>{fmtPercent(row.original.diskPct)}</span>,
      sortingFn: (a, b) => nullableNumberSort(a, b, 'diskPct'), meta: { numeric: true },
    },
    {
      id: 'temp', accessorFn: (device) => device.tempC, header: 'Temp',
      cell: ({ row }) => <span className={(row.original.tempC ?? 0) >= 80 ? 'value-critical' : (row.original.tempC ?? 0) >= 70 ? 'value-warning' : ''}>{fmtTemp(row.original.tempC)}</span>,
      sortingFn: (a, b) => nullableNumberSort(a, b, 'tempC'), meta: { numeric: true },
    },
    {
      id: 'wifi', accessorFn: (device) => device.wifiDbm, header: 'Wi-Fi',
      cell: ({ row }) => <span className={(row.original.wifiDbm ?? 0) <= -80 ? 'value-warning' : ''}>{fmtSignal(row.original.wifiDbm)}</span>,
      sortingFn: (a, b) => nullableNumberSort(a, b, 'wifiDbm'), meta: { numeric: true },
    },
    { id: 'uptime', accessorFn: (device) => device.uptimeSeconds, header: 'Uptime', cell: ({ row }) => fmtUptime(row.original.uptimeSeconds), sortingFn: (a, b) => nullableNumberSort(a, b, 'uptimeSeconds') },
    { id: 'seen', accessorFn: (device) => device.lastSeenSeconds, header: 'Last seen', cell: ({ row }) => fmtAge(row.original.lastSeenSeconds), sortingFn: (a, b) => nullableNumberSort(a, b, 'lastSeenSeconds') },
  ], [])

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Inventory</p>
          <h1>Fleet</h1>
          <p>Search, filter, sort, compare, and open any managed Raspberry Pi.</p>
        </div>
      </div>

      <Panel className="fleet-panel">
        <div className="table-toolbar">
          <label className="search-field">
            <Search aria-hidden="true" />
            <span className="sr-only">Search devices</span>
            <input value={query} onChange={(event) => updateParam('q', event.target.value, '')} placeholder="Search device, group, tag, or version" />
          </label>
          <label className="filter-field">
            <SlidersHorizontal aria-hidden="true" />
            <span>Status</span>
            <select value={status} onChange={(event) => updateParam('status', event.target.value)}>
              <option value="all">All</option>
              <option value="healthy">Healthy</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
              <option value="updating">Updating</option>
              <option value="stale">Stale</option>
              <option value="offline">Offline</option>
            </select>
          </label>
          <label className="filter-field">
            <span>Group</span>
            <select value={group} onChange={(event) => updateParam('group', event.target.value)}>
              <option value="all">All</option>
              {groups.map((name) => <option value={name} key={name}>{name}</option>)}
            </select>
          </label>
          <span className="result-count" role="status">{filtered.length} device{filtered.length === 1 ? '' : 's'}</span>
        </div>

        <div className="fleet-table-wrap" tabIndex={0} aria-label="Managed devices table; scroll horizontally for more columns">
          <table className="fleet-table">
            <caption className="sr-only">Managed LGHS Raspberry Pi fleet</caption>
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const sorted = header.column.getIsSorted()
                    const numeric = Boolean((header.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric)
                    return (
                      <th key={header.id} className={numeric ? 'numeric' : undefined} aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}>
                        {header.isPlaceholder ? null : (
                          <button className="sort-button" type="button" onClick={header.column.getToggleSortingHandler()} disabled={!header.column.getCanSort()}>
                            <span>{flexRender(header.column.columnDef.header, header.getContext())}</span>
                            {sorted === 'asc' ? <ArrowUp aria-hidden="true" /> : sorted === 'desc' ? <ArrowDown aria-hidden="true" /> : <ArrowUpDown aria-hidden="true" />}
                          </button>
                        )}
                      </th>
                    )
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell) => {
                    const numeric = Boolean((cell.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric)
                    return <td key={cell.id} className={numeric ? 'numeric' : undefined}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  })}
                </tr>
              ))}
              {!table.getRowModel().rows.length && (
                <tr><td colSpan={columns.length} className="table-empty">No devices match the current filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
