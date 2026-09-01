import { Activity, Database } from 'lucide-react'

export function EmptyTelemetry() {
  return (
    <div className="telemetry-empty" role="status">
      <div className="telemetry-empty-art" aria-hidden="true">
        <Activity />
        <span />
        <Database />
      </div>
      <div>
        <strong>Historical telemetry is not connected yet</strong>
        <span>Current device metrics are live. Trend charts will appear after the controller history endpoint is enabled.</span>
      </div>
    </div>
  )
}
